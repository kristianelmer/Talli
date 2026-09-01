# Backend system boundary

<!-- architecture-inventory
{"adapterBindingModes":["MarketingMeasurementGateway=>private generated-client transport and SET-only restricted PostgreSQL functions"],"adapterBindingOwners":["MarketingMeasurementGateway=>backend-system"],"adapterBindings":["MarketingMeasurementGateway=>talli_backend.adapters.supabase_marketing_measurement.SupabaseMarketingMeasurementAdapter"],"adapterDependencies":["talli_backend.modules.marketing_measurement.public"],"ports":["MarketingMeasurementGateway"],"publicPackages":["talli_backend.modules.marketing_measurement.public"],"routes":["/api/v1/marketing-measurement/events","/api/v1/marketing-measurement/report","/api/v1/marketing-measurement/withdrawals"],"technicalMigrations":["supabase/migrations/20260828103000_marketing_funnel_measurement.sql"],"technicalTables":["backend_system.marketing_funnel_events","backend_system.marketing_funnel_withdrawals"],"transportDependencies":["asyncio","os","secrets","talli_backend.adapters.supabase_marketing_measurement","talli_backend.modules.marketing_measurement.public"],"workflowDependencies":["talli_backend.modules.marketing_measurement.public"],"workflowPurposes":["marketing-funnel-measurement=>Accepts only consented bounded anonymous funnel codes through a private server transport, deletes withdrawn raw sessions, and returns aggregate-only reports to independently verified active operators."],"workflows":["marketing-funnel-measurement"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["ValidationObservationGateway=>passive post-outcome writer through one SET-only restricted PostgreSQL function"],"adapterBindingOwners":["ValidationObservationGateway=>backend-system"],"adapterBindings":["ValidationObservationGateway=>talli_backend.adapters.supabase_validation_observation.SupabaseValidationObservationAdapter"],"adapterDependencies":["talli_backend.modules.validation_observation.public"],"ports":["ValidationObservationGateway"],"publicPackages":["talli_backend.modules.validation_observation.public"],"routes":["/api/v1/company-access/company-year-admissions"],"technicalMigrations":["supabase/migrations/20260829070411_marketing_measurement_small_cell_threshold.sql","supabase/migrations/20260829074916_validation_observation_authority.sql"],"technicalTables":["backend_system.validation_observation_control","backend_system.validation_observations","backend_system.validation_pilot_entitlements","backend_system.validation_reviewers","backend_system.validation_runs"],"transportDependencies":["talli_backend.adapters.supabase_validation_observation","talli_backend.modules.validation_observation.public","time"],"workflowDependencies":["talli_backend.modules.validation_observation.public"],"workflowPurposes":["passive-validation-observation=>After an admitted company-year outcome is settled, optionally writes one bounded invited-validation record through database-authoritative run and entitlement controls without changing the product response, business state or external calls."],"workflows":["passive-validation-observation"]}
-->

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260829080345_marketing_measurement_consent_proof.sql"],"technicalTables":["backend_system.marketing_consent_actions","backend_system.marketing_measurement_releases"]}
-->

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260827109000_ledger_opening_position_rebuild.sql"]}
-->

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260828100000_banking_capability.sql","supabase/migrations/20260828100500_banking_workflows.sql","supabase/migrations/20260828100600_banking_overlap_trigger_policy.sql","supabase/migrations/20260828102000_banking_connections.sql"],"technicalTables":["backend_system.banking_command_receipts","backend_system.banking_migration_reconciliations","backend_system.banking_migration_runs","backend_system.banking_migration_source_rows"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["BankingPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["BankingPersistence=>backend-system"],"adapterBindings":["BankingPersistence=>talli_backend.adapters.supabase_banking.SupabaseBankingSession"],"adapterDependencies":["talli_backend.adapters.supabase_ledger","talli_backend.application.banking_session","talli_backend.application.banking_workflow","talli_backend.modules.banking.public","talli_backend.modules.ledger.service"],"ports":["BankingPersistence"],"publicPackages":["talli_backend.modules.banking.public"],"transportDependencies":["talli_backend.adapters.supabase_banking","talli_backend.application.banking_session","talli_backend.modules.banking.public"],"workflowDependencies":["talli_backend.modules.banking.public"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["BankDataProvider=>disabled-until-approved read-only Enable Banking fallback adapter with injected transport","BankDataProvider=>disabled-until-approved read-only Neonomics edge adapter with injected transport"],"adapterBindingOwners":["BankDataProvider=>backend-system"],"adapterBindings":["BankDataProvider=>talli_backend.adapters.enable_banking.EnableBankingAdapter","BankDataProvider=>talli_backend.adapters.neonomics_banking.NeonomicsBankingAdapter"],"adapterDependencies":["hashlib","talli_backend.adapters.bank_provider_http","typing"],"ports":["BankDataProvider"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/banking/connections","/api/v1/banking/connections/{connection_id}/accounts/{account_id}/syncs","/api/v1/banking/connections/{connection_id}/callback","/api/v1/banking/connections/{connection_id}/revoke","/api/v1/banking/source-files/previews","/api/v1/banking/source-files/{source_file_id}/acceptance","/api/v1/banking/statement-imports","/api/v1/banking/suggestion-acceptances","/api/v1/banking/transactions"],"workflowPurposes":["banking-reconciliation=>Authenticates one verified actor and runs read-only consent, revocation, durable account sync and recovery, preview-first CSV/CAMT.053 fallback, canonical transaction and acceptance reads, and atomic suggestion acceptance with ledger posting through banking-owned public contracts."],"workflows":["banking-reconciliation"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["SystemBoundaryTransport=>in-process FastAPI composition"],"adapterBindingOwners":["SystemBoundaryTransport=>backend-system"],"adapterBindings":["SystemBoundaryTransport=>talli_backend.main.create_app"],"adapterDependencies":[],"compositionRoots":["apps/backend/src/talli_backend/main.py"],"infrastructure":["durableWorker=>A durable worker consumes persisted delivery state outside the initiating transaction.","eventDelivery=>public.notification_outbox is the persisted event-delivery boundary.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"operationalAdapterRechecks":["true"],"operationalOwners":["backend-system"],"operationalReleaseDecisions":["deny-by-default"],"operationalTables":["public.launch_signoffs"],"ports":["SystemBoundaryTransport"],"publicPackages":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"routes":["/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/context","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/system-boundary/tracer"],"technicalMigrations":["supabase/migrations/0001_authenticated_workspace.sql","supabase/migrations/20260801090000_company_access_invitations.sql","supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql"],"technicalSchemas":["backend_system","public"],"technicalStatements":["These tables implement idempotency, cursor signing, migration evidence, operational control, bounded consented measurement, bounded invited-validation evidence, and event delivery only; they own no accounting, filing, billing, eligibility, acquisition-spend, product-behavior, or authorization decision."],"technicalTables":["backend_system.ledger_command_receipts","backend_system.ledger_cursor_signing_keys","backend_system.ledger_migration_quarantine","backend_system.ledger_migration_reconciliations","backend_system.ledger_migration_runs","backend_system.ledger_migration_source_rows","backend_system.ledger_workflow_receipts","public.company_access_command_receipts","public.launch_signoffs","public.notification_outbox"],"transportDependencies":["__future__","collections","fastapi","fastapi.security","pydantic","re","starlette","talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public","talli_backend.openapi","typing","uuid"],"workflowDependencies":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"workflowPurposes":["company-access-administration=>Runs invitation, reviewer/read-only membership, cancellation, and deletion-review workflows atomically through the company_access public package.","company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"workflows":["company-access-administration","company-access-context","system-boundary-tracer"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["CompanyAccessGateway=>injected Supabase Auth and restricted Postgres adapter","CompanyRegistryGateway=>injected bounded HTTPS public-registry adapter"],"adapterBindingOwners":["CompanyAccessGateway=>backend-system","CompanyRegistryGateway=>backend-system"],"adapterBindings":["CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter","CompanyRegistryGateway=>talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter"],"adapterDependencies":["__future__","asyncio","base64","collections.abc","dataclasses","ipaddress","json","os","psycopg","psycopg.rows","re","talli_backend.modules.company_access.public","urllib.error","urllib.parse","urllib.request"],"ports":["CompanyAccessGateway","CompanyRegistryGateway"],"transportDependencies":["talli_backend.adapters.brreg_company_registry","talli_backend.adapters.supabase_company_access"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/company-access/agreements/reaccept","/api/v1/company-access/companies/{company_id}","/api/v1/company-access/company-year-admissions","/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks","/api/v1/company-access/eligibility/definitive","/api/v1/company-access/eligibility/precheck","/api/v1/company-access/onboarding","/api/v1/company-access/operator-companies","/api/v1/company-access/operator-context","/api/v1/company-access/operator-support-cases/{case_id}","/api/v1/company-access/operator-support-cases/{case_id}/openings","/api/v1/company-access/operator-support-grants","/api/v1/company-access/operator-support-grants/{case_id}/revocations"],"technicalMigrations":["supabase/migrations/20260826100000_company_access_onboarding.sql","supabase/migrations/20260826110000_company_year_admission.sql","supabase/migrations/20260830091341_case_bound_support_access.sql","supabase/migrations/20260830093000_current_legal_evidence.sql"],"workflowPurposes":["company-access-onboarding-and-support=>Retains the fail-closed legacy onboarding response, runs agreement reacceptance and accepted-member lookup, provides backend-only generated case-bound support grant, revoke, explicit open, and read workflows, and temporarily retains an authenticated always-empty deprecated operator-company search response for mixed-revision overlap.","company-year-eligibility-and-admission=>Runs the public provisional company check, definitive manifest-owned interview, authenticated atomic company-year admission, and append-only post-admission safety rechecks through the company_access public package."],"workflows":["company-access-onboarding-and-support","company-year-eligibility-and-admission"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["LedgerPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["LedgerPersistence=>backend-system"],"adapterBindings":["LedgerPersistence=>talli_backend.adapters.supabase_ledger.SupabaseLedgerSession"],"adapterDependencies":["datetime","decimal","talli_backend.application.ledger_session","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.modules.ledger.service","talli_backend.shared.kernel"],"ports":["LedgerPersistence"],"publicPackages":["talli_backend.modules.ledger.public"],"routes":["/api/v1/ledger/administrative-costs","/api/v1/ledger/company-year-close-assessment","/api/v1/ledger/corporate-decisions/finalizations","/api/v1/ledger/entries","/api/v1/ledger/manual-journals","/api/v1/ledger/opening-snapshots","/api/v1/ledger/owner-dividends/payments","/api/v1/ledger/period-locks","/api/v1/ledger/reconstruction-assessment","/api/v1/ledger/shareholder-loans","/api/v1/ledger/tax-settlements","/api/v1/new-year-starts"],"technicalMigrations":["supabase/migrations/20260827100000_ledger_capability.sql","supabase/migrations/20260827100500_ledger_writer_coordinators.sql","supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql","supabase/migrations/20260827103000_ledger_corrections.sql","supabase/migrations/20260827104000_ledger_company_year_close.sql"],"transportDependencies":["datetime","talli_backend.adapters.supabase_ledger","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.shared.kernel"],"workflowDependencies":["talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public"],"workflowPurposes":["ledger-posting-and-period-control=>Authenticates one verified actor and runs intent-specific narrow-ledger posting, immutable source-owned full-year reconstruction and company-year close assessment, cross-capability writer coordination, deterministic cursor queries, the frozen opening-snapshot compatibility read, and compatibility locking without changing a future capability contract."],"workflows":["ledger-posting-and-period-control"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["InvestmentsPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["InvestmentsPersistence=>backend-system"],"adapterBindings":["InvestmentsPersistence=>talli_backend.adapters.supabase_investments.SupabaseInvestmentsSession"],"adapterDependencies":["talli_backend.application.investments_session","talli_backend.application.investments_workflow","talli_backend.modules.investments.public"],"ports":["InvestmentsPersistence"],"publicPackages":["talli_backend.modules.investments.public"],"routes":["/api/v1/investments/acquisition-lots","/api/v1/investments/activity","/api/v1/investments/corrections","/api/v1/investments/positions","/api/v1/investments/received-dividends","/api/v1/investments/received-fund-distributions","/api/v1/investments/share-purchases","/api/v1/investments/share-sale-allocations","/api/v1/investments/share-sales"],"transportDependencies":["decimal","talli_backend.adapters.supabase_investments","talli_backend.application.investments_session","talli_backend.modules.investments.public"],"workflowDependencies":["talli_backend.modules.investments.public"],"workflowPurposes":["investment-activity=>Authenticates one verified actor, records supported domestic purchases, FIFU sales, share dividends, fund distributions, and full-reversal/replacement corrections, posts deterministic entries through ledger in the same transaction, and serves tenant-concealed position, lot, allocation, activity, and correction pages."],"workflows":["investment-activity"]}
-->

<!-- architecture-inventory
{"adapterDependencies":["talli_backend.modules.shareholder_register_filing.public"],"publicPackages":["talli_backend.modules.shareholder_register_filing.public"],"transportDependencies":["talli_backend.modules.shareholder_register_filing.public"],"workflowDependencies":["talli_backend.modules.shareholder_register_filing.public"],"workflowPurposes":["new-year-start=>Coordinates the frozen shareholder-register opening snapshot and ledger opening posting through their public contracts in one backend-owned transaction."],"workflows":["new-year-start"]}
-->

## Purpose

`backend-system.json` is the source of truth for backend composition that no
business capability can own: named workflows, operational control state,
technical persistence, durable infrastructure, and adapter bindings.

## Workflow and public package

The `system-boundary-tracer` workflow serves
`/api/v1/system-boundary/tracer` and may call only
`talli_backend.modules.system_boundary.public`. `main.py` is the single FastAPI
composition root; it does not become a business capability.

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
`talli_backend.modules.ledger.public` with the frozen
`talli_backend.modules.shareholder_register_filing.public` contract in one
backend-owned transaction. The shareholder-register module owns no migrated
data or filing behavior until #151. The application-layer compatibility adapter
translates both intents only inside this workflow's active transaction.

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
`/api/v1/ledger/opening-snapshots`, `/api/v1/ledger/period-locks`,
`/api/v1/ledger/company-year-close-assessment`,
`/api/v1/ledger/reconstruction-assessment`,
`/api/v1/ledger/administrative-costs`,
`/api/v1/ledger/shareholder-loans`, `/api/v1/ledger/tax-settlements`,
`/api/v1/ledger/corporate-decisions/finalizations`,
`/api/v1/ledger/owner-dividends/payments`, and
`/api/v1/ledger/manual-journals`.
It calls `talli_backend.modules.ledger.public` and injects the
`LedgerPersistence` port through
`talli_backend.adapters.supabase_ledger.SupabaseLedgerSession`. Authentication
and transport parsing remain in the application/system boundary. The named
writer coordinators may lock and update frozen future capability records only
inside the same request-bound transaction as their ledger entry. The opening
read stays in an explicitly named compatibility model outside the frozen future
capability package; ledger owns only posting and lock behavior.

The `investment-activity` workflow serves canonical position, acquisition-lot,
FIFU-allocation, activity, and correction pages and accepts domestic share and
fund purchases, share sales, share dividends, fund distributions, and
full-reversal/replacement corrections under `/api/v1/investments`. The
correction and fund-distribution routes are
`/api/v1/investments/corrections` and
`/api/v1/investments/received-fund-distributions`. It calls only the investments
and ledger public contracts. Investments owns validation, FIFU, tax facts,
correction lineage, and persistence; ledger owns the deterministic posting
invoked in the same request-bound transaction.

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
control state. It also owns `public.company_access_command_receipts` and
`backend_system.ledger_command_receipts` and
`backend_system.ledger_workflow_receipts` as technical idempotency state,
`backend_system.ledger_cursor_signing_keys` for opaque cursor integrity,
`backend_system.ledger_migration_runs`,
`backend_system.ledger_migration_source_rows`,
`backend_system.ledger_migration_quarantine`, and
`backend_system.ledger_migration_reconciliations` as cutover evidence, and
`public.notification_outbox` as technical event-delivery state. These tables own
no accounting, filing, billing, or authorization policy.
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
