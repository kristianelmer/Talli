# Backend system boundary

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

## Purpose

`backend-system.json` is the source of truth for backend composition that no
business capability can own: named workflows, operational control state,
technical persistence, durable infrastructure, and adapter bindings.

## Workflow and public package

The `system-boundary-tracer` workflow serves
`/api/v1/system-boundary/tracer` and may call only
`talli_backend.modules.system_boundary.public`. `main.py` is the single FastAPI
composition root; it does not become a business capability.

The `accounting-document-lifecycle` workflow serves
`/api/v1/documents/uploads`, `/api/v1/documents/{document_id}/finalize`,
`/api/v1/documents`, `/api/v1/documents/{document_id}/transfers`,
`/api/v1/documents/{document_id}/remove`, and
`/api/v1/documents/backup-projection` through
`talli_backend.modules.documents.public`. It binds `DocumentsPersistence` to
`talli_backend.adapters.supabase_documents.SupabaseDocumentsPersistence` and
`DocumentObjectStorage` to
`talli_backend.adapters.supabase_documents.SupabaseDocumentObjectStorage`.
`DocumentsAuthorization` binds to
`talli_backend.adapters.supabase_documents.SupabaseDocumentsAuthorization`.

The `billing-and-filing-entitlement` workflow serves billing snapshot,
entitlement, configuration, subscription activation/cancellation,
filing-package purchase/refund, unsupported-case, and pilot-entitlement routes
through `talli_backend.modules.billing.public`. It binds `BillingPersistence`
to `talli_backend.adapters.supabase_billing.SupabaseBillingSession` and
`BillingPaymentProvider` to the production-disabled
`talli_backend.adapters.simulation_billing.SimulationBillingProvider`.

The `marketing-funnel-measurement` workflow serves
`/api/v1/marketing-measurement/events`,
`/api/v1/marketing-measurement/withdrawals`, and
`/api/v1/marketing-measurement/report` through
`talli_backend.modules.marketing_measurement.public`. Ingest and withdrawal
require the private server-to-server generated-client transport. Reports also
require a separately verified active company-access operator, and the database
rechecks that actor before returning aggregate counts, rates, medians, support,
refund, unsupported-exit, and completion signals. No raw session report or
campaign-spend input exists.

The `passive-validation-observation` workflow adds no public control route. Only
after the normal company-year admission result and its persistence and registry
work have settled may composition call
`talli_backend.modules.validation_observation.public`. Exact off mode makes no
call. Invited mode sends one bounded command through the restricted adapter;
PostgreSQL rechecks its own mode, approved run, release and participant-notice
digests, subject-bound entitlement, start, expiry, revocation and withdrawal.
Writer failure cannot alter, retry, roll back or hide the admission result.

The `company-access-context` workflow serves `/api/v1/company-access/context`
and calls only `talli_backend.modules.company_access.public`. It translates a
validated bearer session into the capability's policy-authorized context; it does
not recreate membership, role, resource-scope, AAL2, or tenant-concealment rules.
The composition root injects the declared `CompanyAccessGateway` port through
`talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter`.

The `company-year-eligibility-and-admission` workflow serves the public
`/api/v1/company-access/eligibility/precheck` and
`/api/v1/company-access/eligibility/definitive` routes, the authenticated
`/api/v1/company-access/company-year-admissions` command, and
`/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks`.
It delegates the versioned material-fact boundary, atomic admission, immutable
promise evidence, and post-admission safety gate to the company-access public
package. The composition root maps transport and authentication only.

The `company-access-administration` workflow serves
`/api/v1/company-access/invitations`, `/api/v1/company-access/invitations/lookup`,
`/api/v1/company-access/invitations/accept`,
`/api/v1/company-access/invitations/{invitation_id}/revoke`,
`/api/v1/company-access/invitations/{invitation_id}/resend`,
`/api/v1/company-access/invitation-side-effects/pending`,
`/api/v1/company-access/invitation-side-effects/{operation_id}/complete`,
`/api/v1/company-access/memberships`, and
`/api/v1/company-access/memberships/{user_id}` through the same public package.
It also serves `/api/v1/company-access/cancellations`,
`/api/v1/company-access/cancellations/{cancellation_id}/resume`,
`/api/v1/company-access/cancellations/{cancellation_id}/reviews`, and
`/api/v1/company-access/cancellations/{cancellation_id}/finalize` for the
owner-and-independent-review cancellation lifecycle.

The `company-access-onboarding-and-support` workflow serves
`/api/v1/company-access/onboarding`,
`/api/v1/company-access/agreements/reaccept`,
`/api/v1/company-access/companies/{company_id}`,
`/api/v1/company-access/operator-context`,
`/api/v1/company-access/operator-companies`,
`/api/v1/company-access/operator-support-grants`,
`/api/v1/company-access/operator-support-grants/{case_id}/revocations`,
`/api/v1/company-access/operator-support-cases/{case_id}/openings`, and
`/api/v1/company-access/operator-support-cases/{case_id}`. Its deprecated onboarding route
fails closed and cannot create a company; the workflow otherwise exposes
agreement reacceptance and accepted-member company records. Support uses a
backend-generated case UUID, explicit audited POST opening, read-only GET, exact
company/scope/time/fresh-MFA RLS, and no direct browser table authority. The composition
root retains the deprecated operator-company search only as an authenticated,
always-empty mixed-revision response; it performs no directory lookup or customer-data
read. The composition
root injects `CompanyRegistryGateway` through
`talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter`.

The `new-year-start` workflow serves `/api/v1/new-year-starts` and coordinates
`talli_backend.modules.ledger.public` with
`talli_backend.modules.shareholder_register_filing.public` in one transaction.
RF owns shareholder opening facts. Ledger records the original bank input under
the same snapshot identity, then performs the existing opening posting. The
workflow receipt and both capability writes commit together.

The `banking-reconciliation` workflow serves
the banking connection start/callback/revoke routes, per-account sync route,
source-file preview/acceptance routes, `/api/v1/banking/statement-imports`,
`/api/v1/banking/transactions`, and both methods on
`/api/v1/banking/suggestion-acceptances`. It authenticates a single verified
actor, delegates consent, durable checkpointing, file parsing, deduplication,
suggestion policy, and cursor reads to
`talli_backend.modules.banking.public`, and coordinates an
accepted suggestion with its ledger posting inside one request-bound database
transaction. The web sends only source facts and the canonical expected
suggestion; it cannot choose ledger accounts or lines.

The same system boundary declares `BankDataProvider` and binds
`talli_backend.adapters.neonomics_banking.NeonomicsBankingAdapter` plus
`talli_backend.adapters.enable_banking.EnableBankingAdapter`. Both are
disabled-until-approved read-only edges with injected transports: they normalize
consent, account, pagination, and transaction facts but own no persistence,
ledger command, credential activation, or live-call authority.

The `ledger-posting-and-period-control` workflow serves `/api/v1/ledger/entries`,
`/api/v1/ledger/opening-snapshots`, `/api/v1/ledger/opening-snapshots/by-year`, `/api/v1/ledger/period-locks`,
`/api/v1/ledger/company-year-close-assessment`,
`/api/v1/ledger/reconstruction-assessment`,
`/api/v1/ledger/administrative-costs`,
and `/api/v1/ledger/manual-journals`.
It calls `talli_backend.modules.ledger.public` and injects the
`LedgerPersistence` port through
`talli_backend.adapters.supabase_ledger.SupabaseLedgerSession`. Authentication
and transport parsing remain in the application/system boundary. The named
writer coordinators may lock and update frozen future capability records only
inside the same request-bound transaction as their ledger entry. The opening
read uses the application projection in `application/new_year_opening.py`,
which joins the published RF shareholder and Ledger bank-input reads. Original
snapshot identities, money, ordering and cursor validation remain unchanged.

The `corporate-governance` workflow serves authoritative decision facts,
annual-close and owner-dividend proposal, lifecycle, approval, signing,
attestation, finalization and payment routes plus
`/api/v1/corporate-governance/shareholder-loans` and
`/api/v1/corporate-governance/supported-events`. Corporate
governance owns deterministic Python policy/rendering and canonical immutable
records, verifies Documents evidence, and uses only restricted Ledger and
Banking public contracts for atomic accounting effects.
Its explicit database coordinators register unsigned artifacts, signed copies,
and optional shareholder-loan evidence through the Documents command in the
same transaction as the Governance command; no capability-owned trigger hides
that cross-module write.

The `investment-activity` workflow serves canonical position, acquisition-lot,
FIFU-allocation, activity, economic-event, and correction pages. Domestic share
and fund purchases, share sales, share dividends, and fund distributions are
recognized through `/api/v1/investments/share-purchase-recognitions`,
`/api/v1/investments/share-sale-recognitions`,
`/api/v1/investments/received-dividend-recognitions`, and
`/api/v1/investments/received-fund-distribution-recognitions`. Cash is recorded
later through `/api/v1/investments/cash-settlements`; lifecycle state is read
through `/api/v1/investments/economic-events`; corrections remain at
`/api/v1/investments/corrections`. Document-evidenced values at 31 December are
measured through `/api/v1/investments/year-end-measurements`; any derived
impairment is posted and persisted in the same transaction. The four predecessor mutation paths remain
explicitly deprecated adapters during the ADR-0012 overlap and compose these
same lifecycle commands; they do not reach predecessor workflows or database
writers. It calls the investments, banking, and ledger
public contracts. Before any new or corrected cash settlement is posted, the
workflow submits the immutable bank-fact identity to banking's restricted,
locked claim and requires the canonical company, income year, date, NOK amount
and direction, source hash, and unmatched state to agree before the shared
transaction can commit.
Investments owns FIFU, tax facts, settlement state, year-end measurement,
correction lineage, and
persistence; banking owns canonical transaction facts; ledger owns each
deterministic recognition or settlement posting invoked in the same
request-bound transaction.

## Operational and technical ownership

The banking expand stage adds immutable technical migration evidence in
`backend_system.banking_command_receipts`,
`backend_system.banking_migration_runs`,
`backend_system.banking_migration_source_rows`, and
`backend_system.banking_migration_reconciliations`. These records prove the
exact-ID, count, and canonical-hash transfer performed by
`supabase/migrations/20260828100000_banking_capability.sql` and durable import
idempotency installed by
`supabase/migrations/20260828100500_banking_workflows.sql`; they contain no
banking classification or accounting policy.
`supabase/migrations/20260828100600_banking_overlap_trigger_policy.sql` adds
only trigger-depth mixed-version authority: canonical transactions and
acceptances are projected into their frozen legacy relations, and the
ledger-owned acceptance projector copies the exact already-posted entry lines.
It cannot select an account or admit a canonical command, and contract removes
the projector, grants, policies, triggers, and legacy storage together.
`supabase/migrations/20260828102000_banking_connections.sql` adds forced-RLS
connection, account, sync, coverage, provenance, and encrypted source-file
state. It commits each provider page with its encrypted cursor, keeps provider
facts outside ledger, and requires a persisted file preview before acceptance.

The backend system owns the deny-by-default `public.launch_signoffs` operational
control state. It also owns `public.company_access_command_receipts`,
`billing.billing_command_receipts`, and
`backend_system.ledger_command_receipts` and
`backend_system.ledger_workflow_receipts` as technical idempotency state,
`backend_system.ledger_cursor_signing_keys` for opaque cursor integrity,
`backend_system.ledger_migration_runs`,
`backend_system.ledger_migration_source_rows`,
`backend_system.ledger_migration_quarantine`, and
`backend_system.ledger_migration_reconciliations` as cutover evidence, and
`public.notification_outbox` as technical event-delivery state. These tables own
no accounting, filing, billing policy, or authorization policy.
It also owns `backend_system.marketing_funnel_events` as bounded anonymous
measurement state and `backend_system.marketing_funnel_withdrawals` as a
30-minute replay tombstone, both installed by
`supabase/migrations/20260828103000_marketing_funnel_measurement.sql`. These
tables store no business facts or authorization decision, accept only exact
enums or irreversible session hashes, close an anonymous session after 30
minutes, and expose only security-definer ingest/withdrawal/aggregate functions
to separate SET-only roles. The backend maintenance loop purges expired events
and tombstones at startup and at least hourly while the service is running.
The five-session disclosure correction is installed by
`supabase/migrations/20260829070411_marketing_measurement_small_cell_threshold.sql`.
Durable server-stamped grants and withdrawals, exact first-layer/privacy/release
digest binding, an explicit human-provisioned release gate, and public-session-
only reporting are installed by
`supabase/migrations/20260829080345_marketing_measurement_consent_proof.sql`.
That migration creates no approved release. It revokes the legacy unproved
ingest/report functions from runtime roles, anchors the 30-minute window to the
grant receive time, and counts five distinct sessions rather than five events.

The backend system also owns the five private validation-observation tables.
`validation_observation_control` starts at `off`; migration and startup create no
run, entitlement, reviewer, participant mapping or observation.
`validation_runs`, `validation_pilot_entitlements`, `validation_reviewers` and
`validation_observations` are forced-RLS technical state installed by
`supabase/migrations/20260829074916_validation_observation_authority.sql`.
Separate SET-only roles provision authority, write bounded observations, review
one run, purge expired rows, and inspect launch-off status. The application
backend receives only the writer role.
Their migrations are `supabase/migrations/0001_authenticated_workspace.sql` and
`supabase/migrations/20260801090000_company_access_invitations.sql`, extended by
`supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql`
and `supabase/migrations/20260826100000_company_access_onboarding.sql`.
The atomic company-year admission, immutable promise snapshot, eligibility
assessment, recheck receipt, and restricted executor functions are added by
`supabase/migrations/20260826110000_company_year_admission.sql`.
The ledger command journal, cursor keys, and cutover evidence are added by
`supabase/migrations/20260827100000_ledger_capability.sql` in the
`backend_system` schema. The request-bound prepare/complete coordinators are
added by `supabase/migrations/20260827100500_ledger_writer_coordinators.sql`.
Immutable source-owned full-year reconstruction evidence is added by
`supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql`. The
append-only correction coordinator extends the same technical command receipt
table in `supabase/migrations/20260827103000_ledger_corrections.sql`.
Evidence-gated company-year close assessments extend the receipt table in
`supabase/migrations/20260827104000_ledger_company_year_close.sql`.

## Infrastructure and adapters

Named application workflows use short transactions. Consequential external
operations require durable idempotency before provider I/O, and persisted
`eventDelivery` state is consumed outside the initiating transaction. The
`migrationRunner` owns `supabase/migrations`; a `durableWorker` owns delivery
processing. `SystemBoundaryTransport` is bound only to
`talli_backend.main.create_app`. `CompanyAccessGateway` is bound to the
backend-only authenticated and restricted-Postgres
`talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter`;
`CompanyRegistryGateway` is bound to the bounded HTTPS public-registry adapter.
`MarketingMeasurementGateway` is bound to
`talli_backend.adapters.supabase_marketing_measurement.SupabaseMarketingMeasurementAdapter`
using private generated-client transport and SET-only restricted PostgreSQL
functions.
`ValidationObservationGateway` is bound to
`talli_backend.adapters.supabase_validation_observation.SupabaseValidationObservationAdapter`
and may execute only the one typed passive-writer function.

## Allowed dependencies and change rule

Transport, workflow, and adapter dependency allowlists are in the system
manifest. Adding a workflow, technical table, binding, or dependency changes
this document and `backend-system.json` together, with an ADR review.

## Annual provider boundary (#192, integration pending)

`AnnualBillingProvider` is registered to
`talli_backend.adapters.vipps_billing.VippsTestBillingProvider` in test-origin-only adapter; explicit designated-MT environment composition, disabled by default; no production activation.
The adapter operates only against Vipps MT; registration does not activate
production payments or complete the annual application workflow.

`AnnualCheckoutPersistence` is registered to
`talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCheckoutSession`.
It commits annual purchase/operation claims before external I/O and serializes
settlement against the latest locked purchase and operation. Authenticated annual
HTTP checkout and original-intent recovery are composed through the application;
trusted readiness and the provider remain unavailable by default. Final
source-backed acquisition follows #149/#208 under the approved #192 split.

`AnnualCancellationPersistence` is registered to
`talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCancellationSession`.
It records local renewal cancellation before any provider cleanup. Authenticated
HTTP/runtime composition and receipt-bound cleanup/recovery are implemented.
Automatic source-backed renewal/cleanup processing remains deferred to final #192.

## Annual agreement cleanup persistence

`AnnualAgreementCleanupPersistence` binds to
`talli_backend.adapters.postgres_annual_cleanup.PostgresAnnualCleanupSession`.
It shares the verified-owner PostgreSQL transaction boundary, locks purchase
before operations, binds a persisted cancellation receipt, and settles only the
original cleanup operation. Owner HTTP recovery is composed below; case-bound
operator recovery uses its separately declared restricted support port. Automatic
source-backed cleanup authority remains deferred to final #192.

## Annual billing reads and local cancellation

The `annual-billing-reads-and-cancellation` workflow uses
`SupabaseAnnualBillingAdapter` to verify a bearer and construct read/cancellation
ports from one verified actor. `AnnualBillingWorkflow` imports billing's public
contract only and has no provider/readiness dependency. Snapshot GET reads stored
facts; cancellation POST returns durable local effectiveness and preserved dates.

## Annual checkout and recovery HTTP composition

`AnnualCheckoutWorkflow`, registered in `billing-and-filing-entitlement`, uses the billing public `annual_checkout_operations`
factory and the same independently verified actor's checkout persistence. Start
POST accepts immutable offer/consent choices and an idempotency key. Observation
POST reconciles only the original stored intent; it is POST because reconciliation
may settle durable state. Neither GET nor caller data supplies provider effects,
readiness, merchant identity, price or return destinations. Destinations are
server-owned and preserve company selection.

The explicit checkout-withdrawals POST reuses the original checkout body/key. It
returns a committed withdrawal or the existing purchase reference without any
provider observation or new-sale source resolution. Only confirmed persistence
commit permits an acknowledgement; neither outcome authorizes a replacement sale.

The default composition has no annual provider and raises PROVIDER_DISABLED.
Even with an explicitly injected test provider, its default readiness resolver
raises FILING_NOT_READY and the real PostgreSQL verifier remains unavailable.
These are separate fail-closed boundaries, not #192 checkout acceptance or live
activation. Terminal history replays without provider or new readiness checks,
while current owner/fresh-MFA authorization remains mandatory. Local HTTP test
fixtures do not establish actual MT or authoritative filing readiness.

### Durable annual refund persistence

`AnnualRefundPersistence` is registered to
`talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundSession`.
It shares annual billing's verified-actor transaction, preserves owner versus
explicitly opened billing support-case authority, and commits request/case,
renewal stop, original reservation and cumulative settlement evidence. Its
source resolver is unavailable by default. No refund HTTP route, support caller
or worker is composed; synthetic resolver evidence is not production authority.

The existing `PostgresAnnualCleanupSession` now accepts the exact refund request
that caused renewal to stop as an alternative to a manual cancellation receipt.
It shares the database's private original-charge resolution predicate, including
verified full-refund recovery when checkout remains unknown. Current owner/fresh
MFA and the provider's fresh charge-safety check remain mandatory. Stored original
identity and terminal evidence are retained; no worker/support cleanup caller or
new HTTP operation is composed.

## Annual agreement cleanup HTTP recovery

The `annual-agreement-cleanup` workflow composes billing's public
`AnnualAgreementCleanupOperations` through the verified owner's session. Its POST
accepts only company and purchase IDs and recovers the existing receipt-bound
STOP operation. Default provider is absent; confirmed evidence replays without
provider access, while deferred/unknown remains unresolved. Local cancellation
and history remain provider-free. No worker or support authority is introduced.

## Annual support evidence

The `annual-billing-support` workflow reads stored annual purchases across recorded
years using the verified actor and the explicitly opened same-company billing
support case. It requires current active-admin status and fresh MFA even for an
empty page. Authorization, cursor scope, current purchase totals and related
refund/cleanup summaries share one statement snapshot. No source authority,
provider call, receipt creation or case opening occurs.

The provider-free owner route `/api/v1/billing/annual/refund-snapshot` exposes
purchase balances and recorded refund facts together under the same owner and
fresh-MFA boundary. The predecessor snapshot retains its exact response shape
for mixed-version deployment; the added read does not adjudicate refund rights.

The additive `/api/v1/billing/annual/purchases` route calls the owner history
workflow without a current-admission requirement and exposes no offer. Its
company-scoped cursor spans recorded years under current owner/fresh MFA; the
shared projection remains billing-owned and provider-free.

## Original refund request recovery

The `annual-refund-recovery` workflow authenticates the current owner before
`/api/v1/billing/annual/refund-recoveries`. Billing's
`AnnualRefundRecoveryPersistence` is bound to
`talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundRecoverySession`.
Load and settlement preserve the selected request and require current ownership
and fresh MFA after locks; opened support access never substitutes. The response
contains original-operation status only, without source or provider payloads.
Recovery cannot claim, bind, allocate or execute; provider reconciliation uses the
stored original identity. Provider and source-authority gates remain unchanged.

The existing owner read workflow also exposes
`/api/v1/billing/annual/refund-recovery-targets` through
`AnnualBillingReadPersistence.read_refund_recovery_targets`. The projection is
purchase-scoped and same-actor, owner/fresh-MFA authorized, source/provider free,
and read-only. It groups bound receipts by immutable refund operation order before
pagination and exposes no private source, provider, actor or monetary evidence.
Recovery independently authorizes and validates a selected receipt on explicit POST.

## Annual provider notification intake

The `annual-provider-notification-intake` workflow exposes
`/api/v1/billing/annual/provider-notifications`. It uses
`AnnualNotificationAuthentication` through
`talli_backend.adapters.vipps_webhook.VippsWebhookAuthentication`, followed by
`AnnualNotificationPersistence` through
`talli_backend.adapters.postgres_annual_notifications.PostgresAnnualNotificationInbox`.
Authentication uses the configured MT merchant, secret and callback target;
proxy headers and owner sessions supply no authority. Streaming stops at 64 KiB.
Duplicate header names are rejected before a mapping can collapse them.

`annual_notification_inbox.receipts` is technical event-delivery state,
owned here under ADR0011. It retains only authenticated resource hints and
immutable receipt evidence, including unknown resources. No financial table or
source lookup is performed. `annual_notification_executor` is NOLOGIN, NOINHERIT
and NOBYPASSRLS, receives only bounded receipt-column INSERT and scoped SELECT,
and has no runtime login membership grant. Transaction-local provider/account
settings narrow this already restricted authority; they cannot authorize an owner.
The private `annual_notification_inbox` schema prevents the executor from inheriting access to unrelated PUBLIC-executable functions in the shared technical schema. The separate store owner is for migrations, with no runtime binding.

Receipt insertion and exact duplicate comparison use a short transaction. A
conflict reads the winner in a subsequent statement under READ COMMITTED, then
compares every immutable hint. Acknowledgement follows completed commit; failures
and uncertain commits remain retryable. Success means only durable receipt
acceptance, with no company, purchase or provider details returned. Rollback
withdraws policies and column grants without dropping this independent technical
relation, so delivery identity survives billing rollback and recutover.

The default composition remains unavailable. Registration, credentials, runtime
login authority, purchase resolution, worker leases and original-intent provider
reconciliation remain separate uncompleted #192 work. No callback payload can
confirm payment, grant entitlement or select a refund operation.

## Operator recovery of recorded annual refunds

The `annual-billing-support` workflow adds GET
`/api/v1/billing/annual/support/refund-recovery-targets`, a bounded projection of
operation-bound receipts across requesters in the selected purchase. The separate
`annual-support-refund-recovery` workflow accepts POST
`/api/v1/billing/annual/support/refund-recoveries` with only case, company, purchase
and request IDs. Both derive the operator from the verified session and require
an active admin, fresh MFA and an explicitly opened same-company billing case.

`AnnualSupportRefundRecoveryPersistence` binds to
`talli_backend.adapters.postgres_annual_refund.PostgresAnnualSupportRefundRecoverySession`.
Its load and settlement retain the original requester and operation intent.
The support query survives provider reconciliation and is reauthorized after
lock waits and settlement writes. Exact affected-row checks and final case
validation roll back any partial or denied settlement, including operators who
also have owner rights. There is no owner fallback, new claim, source resolution,
request binding or provider execution in this workflow. The provider remains
absent by default.

## Opt-in annual merchant-test runtime

The composition root uses `talli_backend.adapters.annual_billing_runtime` to
construct the existing Vipps test provider and authenticated technical inbox only
when `TALLI_ANNUAL_BILLING_MODE=vipps-mt` and the complete designated account,
callback and database configuration are valid. Missing or malformed enabled
settings fail startup without revealing secrets. The default remains off.
Explicit provider/intake injection is kept separate from environment composition.

The current designated test sales unit is 535717. Configuration makes no provider
request, creates no credentials or role memberships, and confers no checkout
readiness, filing entitlement, worker or financial-table authority. The existing
source resolver and independent database readiness verifier still fail closed.

The opt-in `apps/backend/scripts/run_annual_checkout_reconciliation.py` entry point
binds the billing observation port to a dedicated restricted database principal.
It runs one public billing operation and exits; no hosted schedule is provisioned.
The technical work table stores only account-scoped leases, fencing, retries and
completion. Billing-owned principal and immutable acceptance records decide which
existing checkout may be observed. New payments, renewals, refund claims, filing
readiness and owner membership are outside this worker.

The annual support agreement-cleanup recovery route binds the recorded STOP
recovery contract to the same explicit billing-case authorization seam as operator
refund recovery. It observes the existing provider intent and cannot create or
execute a cancellation. Purchase money, access, consent and original actor are
preserved.

<!-- architecture-inventory
{"compositionRoots":["apps/backend/src/talli_backend/main.py"],"workflows":["accounting-document-lifecycle","annual-agreement-cleanup","annual-billing-reads-and-cancellation","annual-billing-support","annual-provider-notification-intake","annual-refund-recovery","annual-support-agreement-cleanup-recovery","annual-support-refund-recovery","authority-connections-owner-lifecycle","authority-connections-state","authority-operations","banking-reconciliation","billing-and-filing-entitlement","company-access-administration","company-access-context","company-access-onboarding-and-support","company-year-eligibility-and-admission","corporate-governance","investment-activity","launch-signoff-records","ledger-posting-and-period-control","marketing-funnel-measurement","new-year-start","passive-validation-observation","shareholder-register-filing","system-boundary-tracer"],"workflowPurposes":["accounting-document-lifecycle=>Authenticates one verified actor and owns validated document staging, exact private-object transfers, integrity finalization, tenant-scoped listing, AAL2 download, safe removal restoration, retention metadata, and document-only backup projections.","annual-agreement-cleanup=>Authenticates the current owner to recover one receipt-bound original agreement stop; provider is absent by default, and deferred or unknown outcomes are not confirmation.","annual-billing-reads-and-cancellation=>Authenticates annual owner reads and immediate local renewal cancellation from one verified actor; no provider, readiness or checkout activation.","annual-billing-support=>Reads bounded annual purchase, recorded refund liability and agreement-stop evidence under current active-admin, explicitly opened same-company billing support-case and fresh-MFA authority; never adjudicates refunds or performs side effects.","annual-provider-notification-intake=>Authenticates exact provider delivery bytes and commits immutable technical receipts; no actor, purchase resolution, provider call or financial mutation; disabled by default with explicit designated-MT composition.","annual-refund-recovery=>Authenticates the current owner to reconcile an already operation-bound request made by that actor; no allocation, source resolution or provider execution.","annual-support-agreement-cleanup-recovery=>Reconciles the one already-recorded agreement STOP under current active-admin, explicitly opened same-company billing case and fresh MFA; preserves original receipt and intent and never claims or executes a provider mutation.","annual-support-refund-recovery=>Reconciles an already operation-bound refund under the current active admin's explicitly opened billing case and fresh MFA, preserving the original requester and intent; no new claim, binding or provider execution.","authority-connections-owner-lifecycle=>Preserves the existing owner System User durable start, retry, read and reconcile, plus cookie-only server-authenticated callback recovery without a new fresh-MFA requirement. No provider credential leaves the backend.","authority-connections-state=>Preserves the accepted-request failure effect atomically: lock the owned request, suspend its linked active Billing pilots through the Billing public port, apply the failed state, and recheck the current owner before commit.","authority-operations=>Runs the two existing admin authority operations with fresh MFA at start, fixed production-off-by-default provider configuration, insert-once redacted audit and current-admin completion.","banking-reconciliation=>Authenticates one verified actor and runs read-only consent, revocation, durable account sync and recovery, preview-first CSV/CAMT.053 fallback, canonical transaction and acceptance reads, and atomic suggestion acceptance with ledger posting through banking-owned public contracts.","billing-and-filing-entitlement=>Authenticates one verified actor for annual checkout and original-intent recovery, historical billing cleanup, pilot administration and fail-closed filing entitlement; annual provider and source readiness are unavailable by default.","company-access-administration=>Runs invitation, reviewer/read-only membership, cancellation, and deletion-review workflows atomically through the company_access public package.","company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","company-access-onboarding-and-support=>Retains the fail-closed legacy onboarding response, runs agreement reacceptance and accepted-member lookup, provides backend-only generated case-bound support grant, revoke, explicit open, and read workflows, and temporarily retains an authenticated always-empty deprecated operator-company search response for mixed-revision overlap.","company-year-eligibility-and-admission=>Runs the public provisional company check, definitive manifest-owned interview, authenticated atomic company-year admission, and append-only post-admission safety rechecks through the company_access public package.","corporate-governance=>Authenticates one verified owner, derives deterministic annual-close, owner-dividend, shareholder-loan, supported domestic capital, financing and group-event facts in Python, serves immutable lifecycles, verifies Documents evidence, and atomically coordinates Ledger posting and optional Banking claims through narrow contracts.","investment-activity=>Authenticates one verified actor, recognizes supported domestic purchases, FIFU sales, share dividends and fund distributions independently from cash settlement, validates and single-use claims each settlement against the same actor's canonical unmatched banking fact inside the investment transaction, performs full-reversal/replacement lifecycle corrections and document-evidenced year-end measurement, posts deterministic entries through ledger in the same transaction, and serves tenant-concealed lifecycle, position, lot, allocation, activity, correction, and measurement pages.","launch-signoff-records=>Reads existing technical launch signoffs for current operators and records them for current admins, preserving original fields and validation. Consequential filing adapters independently retain release checks.","ledger-posting-and-period-control=>Authenticates one verified actor and runs intent-specific narrow-ledger posting, immutable source-owned full-year reconstruction and company-year close assessment, cross-capability writer coordination, deterministic cursor queries, the composed RF/Ledger opening-snapshot read, and compatibility locking through declared public contracts.","marketing-funnel-measurement=>Accepts only consented bounded anonymous funnel codes through a private server transport, deletes withdrawn raw sessions, and returns aggregate-only reports to independently verified active operators.","new-year-start=>Coordinates RF-owned opening shareholder facts, the original Ledger bank input and Ledger opening posting in one backend-owned transaction with the same snapshot identity and whole-workflow replay.","passive-validation-observation=>After an admitted company-year outcome is settled, optionally writes one bounded invited-validation record through database-authoritative run and entitlement controls without changing the product response, business state or external calls.","shareholder-register-filing=>Runs authenticated RF preview, review, confirmation, simulation, approval and retained production history through the canonical RF public package; preserves exact owner/MFA/Billing/connection/release gates and the two shipped Send/recovery HTTP contracts.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"routes":["/api/v1/authority-connections/operations","/api/v1/authority-connections/system-user-callbacks","/api/v1/authority-connections/system-user-callbacks","/api/v1/authority-connections/system-user-requests","/api/v1/authority-connections/system-user-requests/reconciliations","/api/v1/authority-connections/system-user-requests/reconciliations","/api/v1/authority-connections/system-user-requests/retries","/api/v1/authority-connections/system-user-requests/retries","/api/v1/banking/connections","/api/v1/banking/connections/{connection_id}/accounts/{account_id}/syncs","/api/v1/banking/connections/{connection_id}/callback","/api/v1/banking/connections/{connection_id}/revoke","/api/v1/banking/source-files/previews","/api/v1/banking/source-files/{source_file_id}/acceptance","/api/v1/banking/statement-imports","/api/v1/banking/suggestion-acceptances","/api/v1/banking/transactions","/api/v1/billing/accounts/configuration","/api/v1/billing/annual/agreement-cleanups","/api/v1/billing/annual/checkout-observations","/api/v1/billing/annual/checkout-preparation","/api/v1/billing/annual/checkout-withdrawals","/api/v1/billing/annual/checkouts","/api/v1/billing/annual/provider-notifications","/api/v1/billing/annual/purchases","/api/v1/billing/annual/refund-recoveries","/api/v1/billing/annual/refund-recovery-targets","/api/v1/billing/annual/refund-snapshot","/api/v1/billing/annual/renewal-cancellations","/api/v1/billing/annual/snapshot","/api/v1/billing/annual/support/agreement-cleanup-recoveries","/api/v1/billing/annual/support/purchases","/api/v1/billing/annual/support/refund-recoveries","/api/v1/billing/annual/support/refund-recovery-targets","/api/v1/billing/entitlement","/api/v1/billing/filing-package/purchase","/api/v1/billing/filing-package/refund","/api/v1/billing/pilot-entitlements","/api/v1/billing/snapshot","/api/v1/billing/subscriptions/activation","/api/v1/billing/subscriptions/cancellation","/api/v1/billing/unsupported","/api/v1/company-access/agreements/reaccept","/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/companies/{company_id}","/api/v1/company-access/company-year-admissions","/api/v1/company-access/company-year-admissions","/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks","/api/v1/company-access/context","/api/v1/company-access/eligibility/definitive","/api/v1/company-access/eligibility/precheck","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/company-access/onboarding","/api/v1/company-access/operator-companies","/api/v1/company-access/operator-context","/api/v1/company-access/operator-support-cases/{case_id}","/api/v1/company-access/operator-support-cases/{case_id}/openings","/api/v1/company-access/operator-support-grants","/api/v1/company-access/operator-support-grants/{case_id}/revocations","/api/v1/corporate-governance/annual-closes/proposals","/api/v1/corporate-governance/annual-closes/{decision_id}/approvals","/api/v1/corporate-governance/annual-closes/{decision_id}/documents","/api/v1/corporate-governance/annual-closes/{decision_id}/events","/api/v1/corporate-governance/annual-closes/{decision_id}/finalizations","/api/v1/corporate-governance/annual-closes/{decision_id}/signed-artifacts","/api/v1/corporate-governance/decision-facts","/api/v1/corporate-governance/decisions","/api/v1/corporate-governance/decisions/{decision_id}","/api/v1/corporate-governance/owner-dividends/proposals","/api/v1/corporate-governance/owner-dividends/{decision_id}/approvals","/api/v1/corporate-governance/owner-dividends/{decision_id}/documents","/api/v1/corporate-governance/owner-dividends/{decision_id}/events","/api/v1/corporate-governance/owner-dividends/{decision_id}/finalizations","/api/v1/corporate-governance/owner-dividends/{decision_id}/payments","/api/v1/corporate-governance/owner-dividends/{decision_id}/signed-artifacts","/api/v1/corporate-governance/readiness","/api/v1/corporate-governance/shareholder-loans","/api/v1/corporate-governance/supported-events","/api/v1/corporate-governance/supported-events/{event_id}/reversal","/api/v1/documents","/api/v1/documents/backup-projection","/api/v1/documents/uploads","/api/v1/documents/{document_id}/finalize","/api/v1/documents/{document_id}/remove","/api/v1/documents/{document_id}/transfers","/api/v1/investments/acquisition-lots","/api/v1/investments/activity","/api/v1/investments/cash-settlements","/api/v1/investments/corrections","/api/v1/investments/economic-events","/api/v1/investments/positions","/api/v1/investments/received-dividend-recognitions","/api/v1/investments/received-dividends","/api/v1/investments/received-fund-distribution-recognitions","/api/v1/investments/received-fund-distributions","/api/v1/investments/share-purchase-recognitions","/api/v1/investments/share-purchases","/api/v1/investments/share-sale-allocations","/api/v1/investments/share-sale-recognitions","/api/v1/investments/share-sales","/api/v1/investments/year-end-measurements","/api/v1/ledger/administrative-costs","/api/v1/ledger/company-year-close-assessment","/api/v1/ledger/entries","/api/v1/ledger/manual-journals","/api/v1/ledger/opening-snapshots","/api/v1/ledger/opening-snapshots/by-year","/api/v1/ledger/period-locks","/api/v1/ledger/reconstruction-assessment","/api/v1/ledger/tax-settlements","/api/v1/legacy-rf1086/feedback-reconciliations","/api/v1/legacy-rf1086/production-filings","/api/v1/marketing-measurement/events","/api/v1/marketing-measurement/report","/api/v1/marketing-measurement/withdrawals","/api/v1/new-year-starts","/api/v1/operator-controls/launch-signoffs","/api/v1/shareholder-register-filings/archive-source","/api/v1/shareholder-register-filings/filing-permissions","/api/v1/shareholder-register-filings/overrides","/api/v1/shareholder-register-filings/previews","/api/v1/shareholder-register-filings/previews/{previewId}","/api/v1/shareholder-register-filings/production-approvals","/api/v1/shareholder-register-filings/review-comment-acknowledgements","/api/v1/shareholder-register-filings/review-comments","/api/v1/shareholder-register-filings/simulations","/api/v1/shareholder-register-filings/test-evidence","/api/v1/shareholder-register-filings/workspace","/api/v1/system-boundary/tracer"],"publicPackages":["talli_backend.modules.authority_connections.public","talli_backend.modules.authority_connections.public","talli_backend.modules.authority_connections.public","talli_backend.modules.banking.public","talli_backend.modules.banking.public","talli_backend.modules.banking.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.billing.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.company_access.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.documents.public","talli_backend.modules.documents.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public","talli_backend.modules.ledger.public","talli_backend.modules.ledger.public","talli_backend.modules.ledger.public","talli_backend.modules.marketing_measurement.public","talli_backend.modules.shareholder_register_filing.public","talli_backend.modules.shareholder_register_filing.public","talli_backend.modules.system_boundary.public","talli_backend.modules.validation_observation.public"],"operationalOwners":["backend-system"],"operationalTables":["public.launch_signoffs"],"operationalReleaseDecisions":["deny-by-default"],"operationalAdapterRechecks":["true"],"technicalSchemas":["annual_notification_inbox","backend_system","public"],"technicalTables":["annual_notification_inbox.receipts","backend_system.annual_checkout_observation_work","backend_system.authority_connections_overlap_grants","backend_system.banking_command_receipts","backend_system.banking_migration_reconciliations","backend_system.banking_migration_runs","backend_system.banking_migration_source_rows","backend_system.ledger_command_receipts","backend_system.ledger_cursor_signing_keys","backend_system.ledger_migration_quarantine","backend_system.ledger_migration_reconciliations","backend_system.ledger_migration_runs","backend_system.ledger_migration_source_rows","backend_system.ledger_workflow_receipts","backend_system.marketing_consent_actions","backend_system.marketing_funnel_events","backend_system.marketing_funnel_withdrawals","backend_system.marketing_measurement_releases","backend_system.validation_observation_control","backend_system.validation_observations","backend_system.validation_pilot_entitlements","backend_system.validation_reviewers","backend_system.validation_runs","billing.billing_command_receipts","public.company_access_command_receipts","public.launch_signoffs","public.notification_outbox","shareholder_register_filing.migration_inventory","shareholder_register_filing.migration_quarantine","shareholder_register_filing.migration_state"],"technicalMigrations":["supabase/contract-migrations/20260902110000_corporate_governance_contract.sql","supabase/contract-migrations/20260905013000_billing_contract.sql","supabase/contract-migrations/20260909190955_shareholder_register_filing_contract.sql","supabase/migrations/0001_authenticated_workspace.sql","supabase/migrations/20260801090000_company_access_invitations.sql","supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql","supabase/migrations/20260826100000_company_access_onboarding.sql","supabase/migrations/20260826110000_company_year_admission.sql","supabase/migrations/20260827100000_ledger_capability.sql","supabase/migrations/20260827100500_ledger_writer_coordinators.sql","supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql","supabase/migrations/20260827103000_ledger_corrections.sql","supabase/migrations/20260827104000_ledger_company_year_close.sql","supabase/migrations/20260827109000_ledger_opening_position_rebuild.sql","supabase/migrations/20260828100000_banking_capability.sql","supabase/migrations/20260828100500_banking_workflows.sql","supabase/migrations/20260828100600_banking_overlap_trigger_policy.sql","supabase/migrations/20260828102000_banking_connections.sql","supabase/migrations/20260828103000_marketing_funnel_measurement.sql","supabase/migrations/20260829070411_marketing_measurement_small_cell_threshold.sql","supabase/migrations/20260829074916_validation_observation_authority.sql","supabase/migrations/20260829080345_marketing_measurement_consent_proof.sql","supabase/migrations/20260830091341_case_bound_support_access.sql","supabase/migrations/20260830093000_current_legal_evidence.sql","supabase/migrations/20260902040000_corporate_governance_owner_dividend.sql","supabase/migrations/20260902053000_corporate_governance_advisor_cleanup.sql","supabase/migrations/20260902054500_corporate_governance_rls_initplan_cleanup.sql","supabase/migrations/20260902070000_corporate_governance_shareholder_loan.sql","supabase/migrations/20260902084230_corporate_governance_shareholder_loan_rls_initplan_cleanup.sql","supabase/migrations/20260902090000_corporate_governance_annual_close.sql","supabase/migrations/20260902095000_company_access_corporate_governance_identity.sql","supabase/migrations/20260902100000_corporate_governance_artifact_lifecycle.sql","supabase/migrations/20260902105000_corporate_governance_hosted_shape_parity.sql","supabase/migrations/20260904220000_corporate_governance_supported_events.sql","supabase/migrations/20260904223000_ledger_supported_event_reversals.sql","supabase/migrations/20260905003000_company_access_billing_owner_subject.sql","supabase/migrations/20260905010000_billing_capability.sql","supabase/migrations/20260906204352_annual_notification_receipts.sql","supabase/migrations/20260907153938_annual_checkout_observation.sql","supabase/migrations/20260909120610_authority_connections_capability.sql","supabase/migrations/20260909124946_backend_system_launch_signoffs.sql","supabase/migrations/20260909190548_shareholder_register_filing_capability.sql","supabase/migrations/20260909190905_shareholder_register_filing_cutover.sql"],"technicalStatements":["These tables implement idempotency, cursor signing, migration evidence, operational control, bounded consented measurement, bounded invited-validation evidence, and event delivery only; they own no accounting, filing, billing policy, eligibility, acquisition-spend, product-behavior, or authorization decision."],"infrastructure":["durableWorker=>The opt-in annual checkout CLI invokes billing public operations once. backend_system.annual_checkout_observation_work owns fenced leases, retries and completion only; billing owns accepted-intent and provider/account authority. No scheduler, provider execution, fabricated owner claims or new business decisions.","eventDelivery=>public.notification_outbox persists outbound deliveries. annual_notification_inbox.receipts retains authenticated annual provider delivery hints and exact-byte replay identity independently of business-table rollback; no business settlement authority.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"ports":["AnnualAgreementCleanupPersistence","AnnualBillingProvider","AnnualBillingReadPersistence","AnnualCancellationPersistence","AnnualCheckoutObservationPersistence","AnnualCheckoutPersistence","AnnualNotificationAuthentication","AnnualNotificationPersistence","AnnualRefundPersistence","AnnualRefundRecoveryPersistence","AnnualSupportCleanupRecoveryPersistence","AnnualSupportReadPersistence","AnnualSupportRefundRecoveryPersistence","AuthorityFailurePilotSuspension","AuthorityOperationsPersistence","AuthorityOperationsProvider","BankDataProvider","BankDataProvider","BankTransactionClaimPersistence","BankTransactionClaimPersistence","BankingPersistence","BillingPaymentProvider","BillingPersistence","CompanyAccessGateway","CompanyRegistryGateway","CorporateGovernancePersistence","DocumentObjectStorage","DocumentsAuthorization","DocumentsPersistence","InvestmentsPersistence","LedgerPersistence","MarketingMeasurementGateway","OpeningSnapshotPersistence","ProductionOperationJournal","Rf1086MutationAuthority","Rf1086PreparationPersistence","Rf1086ProductionJournal","Rf1086ReadOnlyAuthority","SystemBoundaryTransport","SystemUserAuthorityProvider","SystemUserPersistence","SystemUserStateTransaction","ValidationObservationGateway"],"adapterBindings":["AnnualAgreementCleanupPersistence=>talli_backend.adapters.postgres_annual_cleanup.PostgresAnnualCleanupSession","AnnualBillingProvider=>talli_backend.adapters.vipps_billing.VippsTestBillingProvider","AnnualBillingReadPersistence=>talli_backend.adapters.supabase_annual_billing.PostgresAnnualBillingReadSession","AnnualCancellationPersistence=>talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCancellationSession","AnnualCheckoutObservationPersistence=>talli_backend.adapters.postgres_annual_observation.PostgresAnnualCheckoutObservationStore","AnnualCheckoutPersistence=>talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCheckoutSession","AnnualNotificationAuthentication=>talli_backend.adapters.vipps_webhook.VippsWebhookAuthentication","AnnualNotificationPersistence=>talli_backend.adapters.postgres_annual_notifications.PostgresAnnualNotificationInbox","AnnualRefundPersistence=>talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundSession","AnnualRefundRecoveryPersistence=>talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundRecoverySession","AnnualSupportCleanupRecoveryPersistence=>talli_backend.adapters.postgres_annual_support_cleanup.PostgresAnnualSupportCleanupRecoverySession","AnnualSupportReadPersistence=>talli_backend.adapters.postgres_annual_support.PostgresAnnualSupportReadSession","AnnualSupportRefundRecoveryPersistence=>talli_backend.adapters.postgres_annual_refund.PostgresAnnualSupportRefundRecoverySession","AuthorityFailurePilotSuspension=>talli_backend.adapters.postgres_authority_connections._PilotSuspension","AuthorityOperationsPersistence=>talli_backend.adapters.postgres_authority_connections.PostgresAuthorityConnectionsSession","AuthorityOperationsProvider=>talli_backend.adapters.altinn_authority_operations.AltinnAuthorityOperationsAdapter","BankDataProvider=>talli_backend.adapters.enable_banking.EnableBankingAdapter","BankDataProvider=>talli_backend.adapters.neonomics_banking.NeonomicsBankingAdapter","BankTransactionClaimPersistence=>talli_backend.adapters.supabase_corporate_governance.SupabaseCorporateGovernanceTransaction","BankTransactionClaimPersistence=>talli_backend.adapters.supabase_investments.SupabaseInvestmentsTransaction","BankingPersistence=>talli_backend.adapters.supabase_banking.SupabaseBankingSession","BillingPaymentProvider=>talli_backend.adapters.simulation_billing.SimulationBillingProvider","BillingPersistence=>talli_backend.adapters.supabase_billing.SupabaseBillingSession","CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter","CompanyRegistryGateway=>talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter","CorporateGovernancePersistence=>talli_backend.adapters.supabase_corporate_governance.SupabaseCorporateGovernanceSession","DocumentObjectStorage=>talli_backend.adapters.supabase_documents.SupabaseDocumentObjectStorage","DocumentsAuthorization=>talli_backend.adapters.supabase_documents.SupabaseDocumentsAuthorization","DocumentsPersistence=>talli_backend.adapters.supabase_documents.SupabaseDocumentsPersistence","InvestmentsPersistence=>talli_backend.adapters.supabase_investments.SupabaseInvestmentsSession","LedgerPersistence=>talli_backend.adapters.supabase_ledger.SupabaseLedgerSession","MarketingMeasurementGateway=>talli_backend.adapters.supabase_marketing_measurement.SupabaseMarketingMeasurementAdapter","OpeningSnapshotPersistence=>talli_backend.adapters.supabase_ledger.SupabaseLedgerWorkflowTransaction","ProductionOperationJournal=>talli_backend.adapters.postgres_shareholder_register_filing._OperationJournal","Rf1086MutationAuthority=>talli_backend.adapters.rf1086_authority.Rf1086AuthorityAdapter","Rf1086PreparationPersistence=>talli_backend.adapters.postgres_shareholder_register_filing.PostgresShareholderRegisterFilingSession","Rf1086ProductionJournal=>talli_backend.adapters.postgres_shareholder_register_filing._FeedbackJournal","Rf1086ReadOnlyAuthority=>talli_backend.adapters.rf1086_authority.Rf1086ReadOnlyAuthorityAdapter","SystemBoundaryTransport=>talli_backend.main.create_app","SystemUserAuthorityProvider=>talli_backend.adapters.altinn_system_user.AltinnSystemUserAdapter","SystemUserPersistence=>talli_backend.adapters.postgres_authority_connections.PostgresAuthorityConnectionsSession","SystemUserStateTransaction=>talli_backend.adapters.postgres_authority_connections._AuthorityStateTransaction","ValidationObservationGateway=>talli_backend.adapters.supabase_validation_observation.SupabaseValidationObservationAdapter"],"adapterBindingOwners":["AnnualAgreementCleanupPersistence=>backend-system","AnnualBillingProvider=>backend-system","AnnualBillingReadPersistence=>backend-system","AnnualCancellationPersistence=>backend-system","AnnualCheckoutObservationPersistence=>backend-system","AnnualCheckoutPersistence=>backend-system","AnnualNotificationAuthentication=>backend-system","AnnualNotificationPersistence=>backend-system","AnnualRefundPersistence=>backend-system","AnnualRefundRecoveryPersistence=>backend-system","AnnualSupportCleanupRecoveryPersistence=>backend-system","AnnualSupportReadPersistence=>backend-system","AnnualSupportRefundRecoveryPersistence=>backend-system","AuthorityFailurePilotSuspension=>backend-system","AuthorityOperationsPersistence=>backend-system","AuthorityOperationsProvider=>backend-system","BankDataProvider=>backend-system","BankDataProvider=>backend-system","BankTransactionClaimPersistence=>backend-system","BankTransactionClaimPersistence=>backend-system","BankingPersistence=>backend-system","BillingPaymentProvider=>backend-system","BillingPersistence=>backend-system","CompanyAccessGateway=>backend-system","CompanyRegistryGateway=>backend-system","CorporateGovernancePersistence=>backend-system","DocumentObjectStorage=>backend-system","DocumentsAuthorization=>backend-system","DocumentsPersistence=>backend-system","InvestmentsPersistence=>backend-system","LedgerPersistence=>backend-system","MarketingMeasurementGateway=>backend-system","OpeningSnapshotPersistence=>backend-system","ProductionOperationJournal=>backend-system","Rf1086MutationAuthority=>backend-system","Rf1086PreparationPersistence=>backend-system","Rf1086ProductionJournal=>backend-system","Rf1086ReadOnlyAuthority=>backend-system","SystemBoundaryTransport=>backend-system","SystemUserAuthorityProvider=>backend-system","SystemUserPersistence=>backend-system","SystemUserStateTransaction=>backend-system","ValidationObservationGateway=>backend-system"],"adapterBindingModes":["AnnualAgreementCleanupPersistence=>verified-owner receipt-bound original agreement cleanup through authenticated POST; provider absent by default; automatic processing deferred to final #192","AnnualBillingProvider=>test-origin-only adapter; explicit designated-MT environment composition, disabled by default; no production activation","AnnualBillingReadPersistence=>verified-owner stored annual public purchase projection; no provider or readiness calls","AnnualCancellationPersistence=>verified-owner local renewal cancellation and immutable receipts; source-backed renewal and ordinary entitlement deferred to final #192","AnnualCheckoutObservationPersistence=>dedicated account-bound database principal and fenced one-pass reconciliation of committed checkout intent; no provider execution or new claims","AnnualCheckoutPersistence=>restricted verified-actor PostgreSQL original-intent claims and settlement; trusted readiness unavailable until #149/#208 and final #192","AnnualNotificationAuthentication=>designated MT merchant HMAC authentication from explicit complete runtime configuration; disabled by default","AnnualNotificationPersistence=>restricted actorless technical receipt insert/read only; no login grant, purchase lookup, financial write or worker","AnnualRefundPersistence=>verified owner or explicitly opened billing support case; durable refund requests/reservation/settlement; source resolver unavailable by default, no runtime or worker binding","AnnualRefundRecoveryPersistence=>verified current owner/fresh MFA at load and settlement; immutable request and original operation reconciliation only; provider absent by default, no source or claim binding","AnnualSupportCleanupRecoveryPersistence=>opened same-company billing support case with fresh MFA at load, locks and final settlement; one stored STOP only, provider absent by default","AnnualSupportReadPersistence=>verified active-admin opened billing support case; bounded consistent stored annual evidence across years, no provider or source-authority calls","AnnualSupportRefundRecoveryPersistence=>verified active admin with an explicitly opened same-company billing case and fresh MFA at load, settlement and after writes; original bound request and intent retained, provider absent by default","AuthorityFailurePilotSuspension=>Billing-owned fixed pilot suspension in the authority state transaction","AuthorityOperationsPersistence=>verified active admin, fresh MFA at audit start and immutable insert-once operation","AuthorityOperationsProvider=>two fixed production-off-by-default operations, read before write and bounded readback","BankDataProvider=>disabled-until-approved read-only Enable Banking fallback adapter with injected transport","BankDataProvider=>disabled-until-approved read-only Neonomics edge adapter with injected transport","BankTransactionClaimPersistence=>same-request governance transaction using the governance-specific restricted banking claim","BankTransactionClaimPersistence=>same-request investments transaction using the restricted locked banking claim","BankingPersistence=>request-scoped verified-actor restricted PostgreSQL adapter","BillingPaymentProvider=>production-disabled deterministic simulation adapter","BillingPersistence=>request-scoped verified-actor restricted PostgreSQL adapter","CompanyAccessGateway=>injected Supabase Auth and restricted Postgres adapter","CompanyRegistryGateway=>injected bounded HTTPS public-registry adapter","CorporateGovernancePersistence=>request-scoped verified-owner restricted PostgreSQL adapter","DocumentObjectStorage=>backend-only exact-object Supabase Storage adapter","DocumentsAuthorization=>request-scoped accepted-membership facts through the company-access public gateway","DocumentsPersistence=>request-scoped verified-actor restricted PostgreSQL adapter","InvestmentsPersistence=>request-scoped verified-actor restricted PostgreSQL adapter","LedgerPersistence=>request-scoped verified-actor restricted PostgreSQL adapter","MarketingMeasurementGateway=>private generated-client transport and SET-only restricted PostgreSQL functions","OpeningSnapshotPersistence=>verified request-scoped RF capability binding","ProductionOperationJournal=>verified request-scoped RF capability binding","Rf1086MutationAuthority=>verified request-scoped RF capability binding","Rf1086PreparationPersistence=>verified request-scoped RF capability binding","Rf1086ProductionJournal=>verified request-scoped RF capability binding","Rf1086ReadOnlyAuthority=>verified request-scoped RF capability binding","SystemBoundaryTransport=>in-process FastAPI composition","SystemUserAuthorityProvider=>fixed provider endpoints and scoped backend-only delegation, disabled if credentials unavailable","SystemUserPersistence=>verified actor, restricted role, current owner RLS and short committed persistence operations","SystemUserStateTransaction=>same open transaction, request lock then state update and current-owner recheck","ValidationObservationGateway=>passive post-outcome writer through one SET-only restricted PostgreSQL function"],"transportDependencies":["__future__","asyncio","base64","binascii","collections","datetime","decimal","fastapi","fastapi.security","hashlib","os","pydantic","re","secrets","starlette","talli_backend.adapters.altinn_authority_operations","talli_backend.adapters.altinn_system_user","talli_backend.adapters.annual_billing_runtime","talli_backend.adapters.authority_callback_transport","talli_backend.adapters.brreg_company_registry","talli_backend.adapters.postgres_authority_connections","talli_backend.adapters.postgres_launch_signoffs","talli_backend.adapters.postgres_shareholder_register_filing","talli_backend.adapters.simulation_billing","talli_backend.adapters.supabase_annual_billing","talli_backend.adapters.supabase_banking","talli_backend.adapters.supabase_billing","talli_backend.adapters.supabase_company_access","talli_backend.adapters.supabase_corporate_governance","talli_backend.adapters.supabase_documents","talli_backend.adapters.supabase_investments","talli_backend.adapters.supabase_ledger","talli_backend.adapters.supabase_marketing_measurement","talli_backend.adapters.supabase_validation_observation","talli_backend.application.annual_billing","talli_backend.application.annual_notifications","talli_backend.application.authority_connections_session","talli_backend.application.authority_connections_workflow","talli_backend.application.banking_session","talli_backend.application.billing_session","talli_backend.application.billing_workflow","talli_backend.application.corporate_governance_session","talli_backend.application.corporate_governance_workflow","talli_backend.application.investments_session","talli_backend.application.investments_workflow","talli_backend.application.launch_signoffs","talli_backend.application.ledger_workflow","talli_backend.application.new_year_opening","talli_backend.application.shareholder_register_filing_session","talli_backend.application.shareholder_register_filing_workflow","talli_backend.modules.authority_connections.public","talli_backend.modules.banking.public","talli_backend.modules.billing.public","talli_backend.modules.company_access.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public","talli_backend.modules.marketing_measurement.public","talli_backend.modules.shareholder_register_filing.public","talli_backend.modules.system_boundary.public","talli_backend.modules.validation_observation.public","talli_backend.openapi","talli_backend.shared.kernel","time","typing","uuid"],"workflowDependencies":["talli_backend.application.annual_checkout_prerequisites","talli_backend.application.annual_data_compatibility","talli_backend.application.authority_connections_session","talli_backend.application.new_year_opening","talli_backend.application.shareholder_register_filing_session","talli_backend.modules.authority_connections.operations","talli_backend.modules.authority_connections.public","talli_backend.modules.authority_connections.service","talli_backend.modules.banking.public","talli_backend.modules.billing.public","talli_backend.modules.company_access.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public","talli_backend.modules.marketing_measurement.public","talli_backend.modules.shareholder_register_filing.public","talli_backend.modules.system_boundary.public","talli_backend.modules.validation_observation.public"],"adapterDependencies":["__future__","asyncio","base64","collections.abc","cryptography.hazmat.primitives","cryptography.hazmat.primitives.asymmetric","cryptography.hazmat.primitives.serialization","dataclasses","datetime","decimal","hashlib","hmac","httpx","ipaddress","json","os","psycopg","psycopg.conninfo","psycopg.rows","re","talli_backend.adapters.bank_provider_http","talli_backend.adapters.maskinporten","talli_backend.adapters.postgres_annual_notifications","talli_backend.adapters.postgres_annual_observation","talli_backend.adapters.rf1086_authority","talli_backend.adapters.simulation_billing","talli_backend.adapters.supabase_annual_billing","talli_backend.adapters.supabase_billing","talli_backend.adapters.supabase_ledger","talli_backend.adapters.vipps_billing","talli_backend.adapters.vipps_webhook","talli_backend.application.annual_billing","talli_backend.application.annual_data_compatibility","talli_backend.application.annual_notifications","talli_backend.application.authority_connections_session","talli_backend.application.authority_connections_state_workflow","talli_backend.application.banking_session","talli_backend.application.banking_workflow","talli_backend.application.billing_session","talli_backend.application.billing_workflow","talli_backend.application.corporate_governance_session","talli_backend.application.corporate_governance_workflow","talli_backend.application.investments_session","talli_backend.application.investments_workflow","talli_backend.application.launch_signoffs","talli_backend.application.ledger_session","talli_backend.application.ledger_workflow","talli_backend.application.new_year_opening","talli_backend.application.shareholder_register_filing_session","talli_backend.modules.authority_connections.public","talli_backend.modules.banking.public","talli_backend.modules.billing.public","talli_backend.modules.company_access.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public","talli_backend.modules.ledger.service","talli_backend.modules.marketing_measurement.public","talli_backend.modules.shareholder_register_filing.public","talli_backend.modules.validation_observation.public","talli_backend.shared.kernel","time","typing","urllib.error","urllib.parse","urllib.request"]}
-->

## RF capability composition (#151)

The `shareholder-register-filing` workflow composes the canonical RF public
package with Billing, Company Access and Documents. The existing two v1 Send
and recovery paths preserve their exact request/response contracts. Additive
preview, review, confirmation, simulation, approval and workspace reads use the
same authenticated boundary and disable caching, including error responses.

The new-year workflow writes RF share facts and the original Ledger bank input
with the preserved snapshot UUID in one transaction before the existing opening
posting and workflow receipt. The combined read joins the two published SQL
contracts; it never reconstructs the original amount from a current balance.

Migration state, inventory and quarantine in the RF schema remain technical
backend-system bookkeeping. Stored annual-readiness and the original any-obligation
override block are frozen read dependencies through
`backend_system.rf1086_stored_release_inputs_v1`. The fixed six technical signoffs
are checked through `backend_system.rf1086_technical_release_ready_v1`. These
projections preserve the inherited consequential gates without moving sibling
filing rules or writers. The migration evidence ledger records pending scope
approvals and validation; no module declaration constitutes a completed exit gate.

`/api/v1/shareholder-register-filings/archive-source` reads the original year-scoped filing and company-wide review/permission archive inputs through the RF public contract.

Company Tax settlement capture composes `TaxSettlementPersistence`, `TaxSettlementBankingPersistence`, `DocumentBindingPersistence` and `LedgerPersistence` through `talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction`. Expansion and cutover preserve the original backend-system receipt format and actor-scoped RLS. Migration snapshots are technical evidence, not a second business writer: `backend_system.tax_settlement_migration_state`, `backend_system.tax_settlement_migration_inventory`, `backend_system.tax_settlement_source_rows`, `backend_system.tax_settlement_quarantine`, `backend_system.tax_settlement_reconciliations`.

<!-- architecture-inventory
{"technicalTables":["backend_system.tax_settlement_migration_state","backend_system.tax_settlement_migration_inventory","backend_system.tax_settlement_source_rows","backend_system.tax_settlement_quarantine","backend_system.tax_settlement_reconciliations"]}
-->

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260913171000_company_tax_settlement_expand.sql"],"ports":["TaxSettlementPersistence","TaxSettlementBankingPersistence","DocumentBindingPersistence","LedgerPersistence"],"adapterBindings":["TaxSettlementPersistence=>talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction","TaxSettlementBankingPersistence=>talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction","DocumentBindingPersistence=>talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction","LedgerPersistence=>talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction"],"adapterBindingOwners":["TaxSettlementPersistence=>backend-system","TaxSettlementBankingPersistence=>backend-system","DocumentBindingPersistence=>backend-system","LedgerPersistence=>backend-system"],"adapterBindingModes":["TaxSettlementPersistence=>one request-scoped settlement transaction; verified actor, restricted executor and public capability operations","TaxSettlementBankingPersistence=>one request-scoped settlement transaction; verified actor, restricted executor and public capability operations","DocumentBindingPersistence=>one request-scoped settlement transaction; verified actor, restricted executor and public capability operations","LedgerPersistence=>one request-scoped settlement transaction; verified actor, restricted executor and public capability operations"],"workflowDependencies":["talli_backend.application.company_tax_filing_session","talli_backend.modules.company_tax_filing.public"],"adapterDependencies":["talli_backend.application.company_tax_filing_session","talli_backend.modules.company_tax_filing.public","talli_backend.application.company_tax_filing_workflow"]}
-->

The `company-tax-settlement` workflow serves `/api/v1/ledger/tax-settlements` through the Company Tax application with public Ledger, Banking and Documents contracts. It preserves the released route and operation identifier.



<!-- architecture-inventory
{"workflows":["company-tax-settlement"],"workflowPurposes":["company-tax-settlement=>Records tax settlement facts through Company Tax with atomic public Ledger posting, Banking matching and Documents binding; preserves released v1 transport and receipt identity."],"publicPackages":["talli_backend.modules.company_tax_filing.public","talli_backend.modules.ledger.public","talli_backend.modules.banking.public","talli_backend.modules.documents.public"],"transportDependencies":["talli_backend.adapters.postgres_company_tax_filing","talli_backend.application.company_tax_filing_session","talli_backend.modules.company_tax_filing.public"]}
-->

Authenticated `/api/v1/company-tax/settlement-previews` normalizes settlement input through Company Tax and obtains account lines through the Ledger public query. It does not claim a receipt or write data.

<!-- architecture-inventory
{"routes":["/api/v1/company-tax/settlement-previews"]}
-->

Tax cutover inventories standalone source indexes and rollback restores their exact definitions. The canonical table retains company/year and Ledger-reference access paths.

<!-- architecture-inventory
{"technicalMigrations": ["supabase/contract-migrations/20260913172000_company_tax_settlement_cutover.sql"]}
-->

<!-- architecture-inventory
{"ports": ["TaxSettlementArchivePersistence"], "adapterBindings": ["TaxSettlementArchivePersistence=>talli_backend.adapters.postgres_company_tax_filing.PostgresCompanyTaxTransaction"], "adapterBindingOwners": ["TaxSettlementArchivePersistence=>backend-system"], "adapterBindingModes": ["TaxSettlementArchivePersistence=>one request-scoped settlement transaction; verified actor, restricted executor and public capability operations"]}
-->

The Company Tax Archive source authenticates one company/year and preserves original source-row fields through the public query port.

<!-- architecture-inventory
{"routes":["/api/v1/company-tax/settlement-archive-source"]}
-->

The final Tax contract retires the exclusive old projection after Archive and readiness reads move to the owned query. Both rollback forms preserve source and canonical rows and keep one writer.

<!-- architecture-inventory
{"technicalMigrations": ["supabase/contract-migrations/20260913173000_company_tax_settlement_contract.sql"]}
-->
