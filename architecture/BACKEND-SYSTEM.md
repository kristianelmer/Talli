# Backend system boundary

<!-- architecture-inventory
{"adapterBindingModes":["MarketingMeasurementGateway=>private generated-client transport and SET-only restricted PostgreSQL functions"],"adapterBindingOwners":["MarketingMeasurementGateway=>backend-system"],"adapterBindings":["MarketingMeasurementGateway=>talli_backend.adapters.supabase_marketing_measurement.SupabaseMarketingMeasurementAdapter"],"adapterDependencies":["talli_backend.modules.marketing_measurement.public"],"ports":["MarketingMeasurementGateway"],"publicPackages":["talli_backend.modules.marketing_measurement.public"],"routes":["/api/v1/marketing-measurement/events","/api/v1/marketing-measurement/report","/api/v1/marketing-measurement/withdrawals"],"technicalMigrations":["supabase/migrations/20260828103000_marketing_funnel_measurement.sql"],"technicalTables":["backend_system.marketing_funnel_events","backend_system.marketing_funnel_withdrawals"],"transportDependencies":["asyncio","os","secrets","talli_backend.adapters.supabase_marketing_measurement","talli_backend.modules.marketing_measurement.public"],"workflowDependencies":["talli_backend.modules.marketing_measurement.public"],"workflowPurposes":["marketing-funnel-measurement=>Accepts only consented bounded anonymous funnel codes through a private server transport, deletes withdrawn raw sessions, and returns aggregate-only reports to independently verified active operators."],"workflows":["marketing-funnel-measurement"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/corporate-governance/supported-events/{event_id}/reversal"],"technicalMigrations":["supabase/migrations/20260904223000_ledger_supported_event_reversals.sql"]}
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
{"adapterBindingModes":["SystemBoundaryTransport=>in-process FastAPI composition"],"adapterBindingOwners":["SystemBoundaryTransport=>backend-system"],"adapterBindings":["SystemBoundaryTransport=>talli_backend.main.create_app"],"adapterDependencies":[],"compositionRoots":["apps/backend/src/talli_backend/main.py"],"infrastructure":["durableWorker=>A durable worker consumes persisted delivery state outside the initiating transaction.","eventDelivery=>public.notification_outbox persists outbound deliveries. annual_notification_inbox.receipts retains authenticated annual provider delivery hints and exact-byte replay identity independently of business-table rollback; no business settlement authority.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"operationalAdapterRechecks":["true"],"operationalOwners":["backend-system"],"operationalReleaseDecisions":["deny-by-default"],"operationalTables":["public.launch_signoffs"],"ports":["SystemBoundaryTransport"],"publicPackages":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"routes":["/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/context","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/system-boundary/tracer"],"technicalMigrations":["supabase/migrations/0001_authenticated_workspace.sql","supabase/migrations/20260801090000_company_access_invitations.sql","supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql","supabase/migrations/20260905010000_billing_capability.sql"],"technicalSchemas":["backend_system","public"],"technicalStatements":["These tables implement idempotency, cursor signing, migration evidence, operational control, bounded consented measurement, bounded invited-validation evidence, and event delivery only; they own no accounting, filing, billing policy, eligibility, acquisition-spend, product-behavior, or authorization decision."],"technicalTables":["backend_system.ledger_command_receipts","backend_system.ledger_cursor_signing_keys","backend_system.ledger_migration_quarantine","backend_system.ledger_migration_reconciliations","backend_system.ledger_migration_runs","backend_system.ledger_migration_source_rows","backend_system.ledger_workflow_receipts","billing.billing_command_receipts","public.company_access_command_receipts","public.launch_signoffs","public.notification_outbox"],"transportDependencies":["__future__","collections","fastapi","fastapi.security","pydantic","re","starlette","talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public","talli_backend.openapi","typing","uuid"],"workflowDependencies":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"workflowPurposes":["company-access-administration=>Runs invitation, reviewer/read-only membership, cancellation, and deletion-review workflows atomically through the company_access public package.","company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"workflows":["company-access-administration","company-access-context","system-boundary-tracer"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["CompanyAccessGateway=>injected Supabase Auth and restricted Postgres adapter","CompanyRegistryGateway=>injected bounded HTTPS public-registry adapter"],"adapterBindingOwners":["CompanyAccessGateway=>backend-system","CompanyRegistryGateway=>backend-system"],"adapterBindings":["CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter","CompanyRegistryGateway=>talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter"],"adapterDependencies":["__future__","asyncio","base64","collections.abc","dataclasses","ipaddress","json","os","psycopg","psycopg.rows","re","talli_backend.modules.company_access.public","urllib.error","urllib.parse","urllib.request"],"ports":["CompanyAccessGateway","CompanyRegistryGateway"],"transportDependencies":["talli_backend.adapters.brreg_company_registry","talli_backend.adapters.supabase_company_access"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/company-access/agreements/reaccept","/api/v1/company-access/companies/{company_id}","/api/v1/company-access/company-year-admissions","/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks","/api/v1/company-access/eligibility/definitive","/api/v1/company-access/eligibility/precheck","/api/v1/company-access/onboarding","/api/v1/company-access/operator-companies","/api/v1/company-access/operator-context","/api/v1/company-access/operator-support-cases/{case_id}","/api/v1/company-access/operator-support-cases/{case_id}/openings","/api/v1/company-access/operator-support-grants","/api/v1/company-access/operator-support-grants/{case_id}/revocations"],"technicalMigrations":["supabase/migrations/20260826100000_company_access_onboarding.sql","supabase/migrations/20260826110000_company_year_admission.sql","supabase/migrations/20260830091341_case_bound_support_access.sql","supabase/migrations/20260830093000_current_legal_evidence.sql","supabase/migrations/20260902095000_company_access_corporate_governance_identity.sql","supabase/migrations/20260905003000_company_access_billing_owner_subject.sql"],"workflowPurposes":["company-access-onboarding-and-support=>Retains the fail-closed legacy onboarding response, runs agreement reacceptance and accepted-member lookup, provides backend-only generated case-bound support grant, revoke, explicit open, and read workflows, and temporarily retains an authenticated always-empty deprecated operator-company search response for mixed-revision overlap.","company-year-eligibility-and-admission=>Runs the public provisional company check, definitive manifest-owned interview, authenticated atomic company-year admission, and append-only post-admission safety rechecks through the company_access public package."],"workflows":["company-access-onboarding-and-support","company-year-eligibility-and-admission"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["LedgerPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["LedgerPersistence=>backend-system"],"adapterBindings":["LedgerPersistence=>talli_backend.adapters.supabase_ledger.SupabaseLedgerSession"],"adapterDependencies":["datetime","decimal","talli_backend.application.ledger_session","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.modules.ledger.service","talli_backend.shared.kernel"],"ports":["LedgerPersistence"],"publicPackages":["talli_backend.modules.ledger.public"],"routes":["/api/v1/ledger/administrative-costs","/api/v1/ledger/company-year-close-assessment","/api/v1/ledger/entries","/api/v1/ledger/manual-journals","/api/v1/ledger/opening-snapshots","/api/v1/ledger/period-locks","/api/v1/ledger/reconstruction-assessment","/api/v1/ledger/tax-settlements","/api/v1/new-year-starts"],"technicalMigrations":["supabase/migrations/20260827100000_ledger_capability.sql","supabase/migrations/20260827100500_ledger_writer_coordinators.sql","supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql","supabase/migrations/20260827103000_ledger_corrections.sql","supabase/migrations/20260827104000_ledger_company_year_close.sql"],"transportDependencies":["datetime","talli_backend.adapters.supabase_ledger","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.shared.kernel"],"workflowDependencies":["talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public"],"workflowPurposes":["ledger-posting-and-period-control=>Authenticates one verified actor and runs intent-specific narrow-ledger posting, immutable source-owned full-year reconstruction and company-year close assessment, cross-capability writer coordination, deterministic cursor queries, the frozen opening-snapshot compatibility read, and compatibility locking without changing a future capability contract."],"workflows":["ledger-posting-and-period-control"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["BankTransactionClaimPersistence=>same-request investments transaction using the restricted locked banking claim","InvestmentsPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["BankTransactionClaimPersistence=>backend-system","InvestmentsPersistence=>backend-system"],"adapterBindings":["BankTransactionClaimPersistence=>talli_backend.adapters.supabase_investments.SupabaseInvestmentsTransaction","InvestmentsPersistence=>talli_backend.adapters.supabase_investments.SupabaseInvestmentsSession"],"adapterDependencies":["talli_backend.application.investments_session","talli_backend.application.investments_workflow","talli_backend.modules.banking.public","talli_backend.modules.investments.public"],"ports":["BankTransactionClaimPersistence","InvestmentsPersistence"],"publicPackages":["talli_backend.modules.banking.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public"],"routes":["/api/v1/investments/acquisition-lots","/api/v1/investments/activity","/api/v1/investments/cash-settlements","/api/v1/investments/corrections","/api/v1/investments/economic-events","/api/v1/investments/positions","/api/v1/investments/received-dividend-recognitions","/api/v1/investments/received-dividends","/api/v1/investments/received-fund-distribution-recognitions","/api/v1/investments/received-fund-distributions","/api/v1/investments/share-purchase-recognitions","/api/v1/investments/share-purchases","/api/v1/investments/share-sale-allocations","/api/v1/investments/share-sale-recognitions","/api/v1/investments/share-sales","/api/v1/investments/year-end-measurements"],"transportDependencies":["decimal","hashlib","talli_backend.adapters.supabase_investments","talli_backend.application.investments_session","talli_backend.modules.banking.public","talli_backend.modules.investments.public"],"workflowDependencies":["talli_backend.modules.banking.public","talli_backend.modules.investments.public","talli_backend.modules.ledger.public"],"workflowPurposes":["investment-activity=>Authenticates one verified actor, recognizes supported domestic purchases, FIFU sales, share dividends and fund distributions independently from cash settlement, validates and single-use claims each settlement against the same actor's canonical unmatched banking fact inside the investment transaction, performs full-reversal/replacement lifecycle corrections and document-evidenced year-end measurement, posts deterministic entries through ledger in the same transaction, and serves tenant-concealed lifecycle, position, lot, allocation, activity, correction, and measurement pages."],"workflows":["investment-activity"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["BankTransactionClaimPersistence=>same-request governance transaction using the governance-specific restricted banking claim","CorporateGovernancePersistence=>request-scoped verified-owner restricted PostgreSQL adapter"],"adapterBindingOwners":["BankTransactionClaimPersistence=>backend-system","CorporateGovernancePersistence=>backend-system"],"adapterBindings":["BankTransactionClaimPersistence=>talli_backend.adapters.supabase_corporate_governance.SupabaseCorporateGovernanceTransaction","CorporateGovernancePersistence=>talli_backend.adapters.supabase_corporate_governance.SupabaseCorporateGovernanceSession"],"adapterDependencies":["talli_backend.application.corporate_governance_session","talli_backend.application.corporate_governance_workflow","talli_backend.modules.banking.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.ledger.public"],"ports":["BankTransactionClaimPersistence","CorporateGovernancePersistence"],"publicPackages":["talli_backend.modules.banking.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.ledger.public"],"routes":["/api/v1/corporate-governance/annual-closes/proposals","/api/v1/corporate-governance/annual-closes/{decision_id}/approvals","/api/v1/corporate-governance/annual-closes/{decision_id}/documents","/api/v1/corporate-governance/annual-closes/{decision_id}/events","/api/v1/corporate-governance/annual-closes/{decision_id}/finalizations","/api/v1/corporate-governance/annual-closes/{decision_id}/signed-artifacts","/api/v1/corporate-governance/decision-facts","/api/v1/corporate-governance/decisions","/api/v1/corporate-governance/decisions/{decision_id}","/api/v1/corporate-governance/readiness","/api/v1/corporate-governance/shareholder-loans","/api/v1/corporate-governance/supported-events","/api/v1/corporate-governance/owner-dividends/proposals","/api/v1/corporate-governance/owner-dividends/{decision_id}/approvals","/api/v1/corporate-governance/owner-dividends/{decision_id}/documents","/api/v1/corporate-governance/owner-dividends/{decision_id}/events","/api/v1/corporate-governance/owner-dividends/{decision_id}/finalizations","/api/v1/corporate-governance/owner-dividends/{decision_id}/payments","/api/v1/corporate-governance/owner-dividends/{decision_id}/signed-artifacts"],"technicalMigrations":["supabase/migrations/20260902040000_corporate_governance_owner_dividend.sql","supabase/migrations/20260902053000_corporate_governance_advisor_cleanup.sql","supabase/migrations/20260902054500_corporate_governance_rls_initplan_cleanup.sql","supabase/migrations/20260902070000_corporate_governance_shareholder_loan.sql","supabase/migrations/20260902084230_corporate_governance_shareholder_loan_rls_initplan_cleanup.sql","supabase/migrations/20260902090000_corporate_governance_annual_close.sql","supabase/migrations/20260902100000_corporate_governance_artifact_lifecycle.sql","supabase/migrations/20260902105000_corporate_governance_hosted_shape_parity.sql","supabase/migrations/20260904220000_corporate_governance_supported_events.sql","supabase/contract-migrations/20260902110000_corporate_governance_contract.sql"],"transportDependencies":["talli_backend.adapters.supabase_corporate_governance","talli_backend.application.corporate_governance_session","talli_backend.modules.corporate_governance.public"],"workflowDependencies":["talli_backend.modules.banking.public","talli_backend.modules.corporate_governance.public","talli_backend.modules.documents.public","talli_backend.modules.ledger.public"],"workflowPurposes":["corporate-governance=>Authenticates one verified owner, derives deterministic annual-close, owner-dividend, shareholder-loan, supported domestic capital, financing and group-event facts in Python, serves immutable lifecycles, verifies Documents evidence, and atomically coordinates Ledger posting and optional Banking claims through narrow contracts."],"workflows":["corporate-governance"]}
-->

<!-- architecture-inventory
{"adapterDependencies":["talli_backend.application.annual_data_compatibility"],"publicPackages":["talli_backend.modules.company_access.public"],"transportDependencies":["talli_backend.application.corporate_governance_workflow"],"workflowDependencies":["talli_backend.application.annual_data_compatibility","talli_backend.modules.company_access.public"]}
-->

<!-- architecture-inventory
{"adapterDependencies":["talli_backend.modules.shareholder_register_filing.public"],"publicPackages":["talli_backend.modules.shareholder_register_filing.public"],"transportDependencies":["talli_backend.modules.shareholder_register_filing.public"],"workflowDependencies":["talli_backend.modules.shareholder_register_filing.public"],"workflowPurposes":["new-year-start=>Coordinates the frozen shareholder-register opening snapshot and ledger opening posting through their public contracts in one backend-owned transaction."],"workflows":["new-year-start"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["DocumentObjectStorage=>backend-only exact-object Supabase Storage adapter","DocumentsAuthorization=>request-scoped accepted-membership facts through the company-access public gateway","DocumentsPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["DocumentObjectStorage=>backend-system","DocumentsAuthorization=>backend-system","DocumentsPersistence=>backend-system"],"adapterBindings":["DocumentObjectStorage=>talli_backend.adapters.supabase_documents.SupabaseDocumentObjectStorage","DocumentsAuthorization=>talli_backend.adapters.supabase_documents.SupabaseDocumentsAuthorization","DocumentsPersistence=>talli_backend.adapters.supabase_documents.SupabaseDocumentsPersistence"],"adapterDependencies":["talli_backend.modules.documents.public"],"ports":["DocumentObjectStorage","DocumentsAuthorization","DocumentsPersistence"],"publicPackages":["talli_backend.modules.documents.public"],"routes":["/api/v1/documents","/api/v1/documents/backup-projection","/api/v1/documents/uploads","/api/v1/documents/{document_id}/finalize","/api/v1/documents/{document_id}/remove","/api/v1/documents/{document_id}/transfers"],"transportDependencies":["base64","binascii","talli_backend.adapters.supabase_documents","talli_backend.modules.documents.public"],"workflowDependencies":["talli_backend.modules.documents.public"],"workflowPurposes":["accounting-document-lifecycle=>Authenticates one verified actor and owns validated document staging, exact private-object transfers, integrity finalization, tenant-scoped listing, AAL2 download, safe removal restoration, retention metadata, and document-only backup projections."],"workflows":["accounting-document-lifecycle"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["BillingPaymentProvider=>production-disabled deterministic simulation adapter","BillingPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["BillingPaymentProvider=>backend-system","BillingPersistence=>backend-system"],"adapterBindings":["BillingPaymentProvider=>talli_backend.adapters.simulation_billing.SimulationBillingProvider","BillingPersistence=>talli_backend.adapters.supabase_billing.SupabaseBillingSession"],"adapterDependencies":["talli_backend.adapters.simulation_billing","talli_backend.adapters.supabase_billing","talli_backend.application.billing_session","talli_backend.application.billing_workflow","talli_backend.modules.billing.public"],"ports":["BillingPaymentProvider","BillingPersistence"],"publicPackages":["talli_backend.modules.billing.public"],"routes":["/api/v1/billing/accounts/configuration","/api/v1/billing/entitlement","/api/v1/billing/filing-package/purchase","/api/v1/billing/filing-package/refund","/api/v1/billing/pilot-entitlements","/api/v1/billing/snapshot","/api/v1/billing/subscriptions/activation","/api/v1/billing/subscriptions/cancellation","/api/v1/billing/unsupported"],"technicalMigrations":["supabase/contract-migrations/20260905013000_billing_contract.sql","supabase/migrations/20260905010000_billing_capability.sql"],"transportDependencies":["talli_backend.adapters.simulation_billing","talli_backend.adapters.supabase_billing","talli_backend.application.billing_session","talli_backend.application.billing_workflow","talli_backend.modules.billing.public"],"workflowDependencies":["talli_backend.modules.billing.public"],"workflowPurposes":["billing-and-filing-entitlement=>Authenticates one verified actor for annual checkout and original-intent recovery, historical billing cleanup, pilot administration and fail-closed filing entitlement; annual provider and source readiness are unavailable by default."],"workflows":["billing-and-filing-entitlement"]}
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
`/api/v1/ledger/administrative-costs`, `/api/v1/ledger/tax-settlements`,
and `/api/v1/ledger/manual-journals`.
It calls `talli_backend.modules.ledger.public` and injects the
`LedgerPersistence` port through
`talli_backend.adapters.supabase_ledger.SupabaseLedgerSession`. Authentication
and transport parsing remain in the application/system boundary. The named
writer coordinators may lock and update frozen future capability records only
inside the same request-bound transaction as their ledger entry. The opening
read stays in an explicitly named compatibility model outside the frozen future
capability package; ledger owns only posting and lock behavior.

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

<!-- architecture-inventory
{"transportDependencies":["talli_backend.application.investments_workflow"]}
-->

## Annual provider boundary (#192, integration pending)

`AnnualBillingProvider` is registered to
`talli_backend.adapters.vipps_billing.VippsTestBillingProvider` in test-origin-only adapter; runtime composition pending #192, no production activation.
The adapter operates only against Vipps MT; registration does not activate
production payments or complete the annual application workflow.

<!-- architecture-inventory
{"ports":["AnnualBillingProvider"],"adapterBindings":["AnnualBillingProvider=>talli_backend.adapters.vipps_billing.VippsTestBillingProvider"],"adapterBindingOwners":["AnnualBillingProvider=>backend-system"],"adapterBindingModes":["AnnualBillingProvider=>test-origin-only adapter; runtime composition pending #192, no production activation"]}
-->

`AnnualCheckoutPersistence` is registered to
`talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCheckoutSession`.
It commits annual purchase/operation claims before external I/O and serializes
settlement against the latest locked purchase and operation. Readiness defaults
to unavailable; no annual HTTP/runtime composition is enabled by this adapter.

<!-- architecture-inventory
{"ports":["AnnualCheckoutPersistence"],"adapterBindings":["AnnualCheckoutPersistence=>talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCheckoutSession"],"adapterBindingOwners":["AnnualCheckoutPersistence=>backend-system"],"adapterBindingModes":["AnnualCheckoutPersistence=>restricted verified-actor PostgreSQL claims and settlement; readiness defaults unavailable; runtime cutover pending #192"]}
-->

`AnnualCancellationPersistence` is registered to
`talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCancellationSession`.
It records local renewal cancellation before any provider cleanup. HTTP/runtime
composition, provider cleanup and worker recovery remain pending.

<!-- architecture-inventory
{"ports":["AnnualCancellationPersistence"],"adapterBindings":["AnnualCancellationPersistence=>talli_backend.adapters.postgres_annual_checkout.PostgresAnnualCancellationSession"],"adapterBindingOwners":["AnnualCancellationPersistence=>backend-system"],"adapterBindingModes":["AnnualCancellationPersistence=>verified-owner local renewal cancellation and immutable receipts; provider cleanup and runtime cutover pending #192"]}
-->


## Annual agreement cleanup persistence

`AnnualAgreementCleanupPersistence` binds to
`talli_backend.adapters.postgres_annual_cleanup.PostgresAnnualCleanupSession`.
It shares the verified-owner PostgreSQL transaction boundary, locks purchase
before operations, binds a persisted cancellation receipt, and settles only the
original cleanup operation. Owner HTTP recovery is composed below; worker and
support authority remain pending #192.

<!-- architecture-inventory
{"ports":["AnnualAgreementCleanupPersistence"],"adapterBindings":["AnnualAgreementCleanupPersistence=>talli_backend.adapters.postgres_annual_cleanup.PostgresAnnualCleanupSession"],"adapterBindingOwners":["AnnualAgreementCleanupPersistence=>backend-system"],"adapterBindingModes":["AnnualAgreementCleanupPersistence=>verified-owner receipt-bound original agreement cleanup through authenticated POST; provider absent by default, worker/support authority pending #192"]}
-->


## Annual billing reads and local cancellation

The `annual-billing-reads-and-cancellation` workflow uses
`SupabaseAnnualBillingAdapter` to verify a bearer and construct read/cancellation
ports from one verified actor. `AnnualBillingWorkflow` imports billing's public
contract only and has no provider/readiness dependency. Snapshot GET reads stored
facts; cancellation POST returns durable local effectiveness and preserved dates.

<!-- architecture-inventory
{"workflows":["annual-billing-reads-and-cancellation"],"routes":["/api/v1/billing/annual/snapshot","/api/v1/billing/annual/purchases", "/api/v1/billing/annual/refund-snapshot","/api/v1/billing/annual/refund-recovery-targets","/api/v1/billing/annual/renewal-cancellations"],"ports":["AnnualBillingReadPersistence"],"adapterBindings":["AnnualBillingReadPersistence=>talli_backend.adapters.supabase_annual_billing.PostgresAnnualBillingReadSession"],"adapterBindingOwners":["AnnualBillingReadPersistence=>backend-system"],"adapterBindingModes":["AnnualBillingReadPersistence=>verified-owner stored annual public purchase projection; no provider or readiness calls"]}
-->


<!-- architecture-inventory
{"workflowPurposes":["annual-billing-reads-and-cancellation=>Authenticates annual owner reads and immediate local renewal cancellation from one verified actor; no provider, readiness or checkout activation."],"transportDependencies":["talli_backend.adapters.supabase_annual_billing","talli_backend.application.annual_billing"],"adapterDependencies":["talli_backend.adapters.supabase_annual_billing","talli_backend.application.annual_billing"]}
-->


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

<!-- architecture-inventory
{"routes":["/api/v1/billing/annual/checkout-withdrawals","/api/v1/billing/annual/checkout-preparation","/api/v1/billing/annual/checkouts","/api/v1/billing/annual/checkout-observations"],"workflowDependencies":["talli_backend.application.annual_checkout_prerequisites"]}
-->


### Durable annual refund persistence

`AnnualRefundPersistence` is registered to
`talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundSession`.
It shares annual billing's verified-actor transaction, preserves owner versus
explicitly opened billing support-case authority, and commits request/case,
renewal stop, original reservation and cumulative settlement evidence. Its
source resolver is unavailable by default. No refund HTTP route, support caller
or worker is composed; synthetic resolver evidence is not production authority.

<!-- architecture-inventory
{"ports":["AnnualRefundPersistence"],"adapterBindings":["AnnualRefundPersistence=>talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundSession"],"adapterBindingOwners":["AnnualRefundPersistence=>backend-system"],"adapterBindingModes":["AnnualRefundPersistence=>verified owner or explicitly opened billing support case; durable refund requests/reservation/settlement; source resolver unavailable by default, no runtime or worker binding"]}
-->


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

<!-- architecture-inventory
{"workflows":["annual-agreement-cleanup"],"workflowPurposes":["annual-agreement-cleanup=>Authenticates the current owner to recover one receipt-bound original agreement stop; provider is absent by default, and deferred or unknown outcomes are not confirmation."],"publicPackages":["talli_backend.modules.billing.public"],"routes":["/api/v1/billing/annual/agreement-cleanups"]}
-->

## Annual support evidence

The `annual-billing-support` workflow reads stored annual purchases across recorded
years using the verified actor and the explicitly opened same-company billing
support case. It requires current active-admin status and fresh MFA even for an
empty page. Authorization, cursor scope, current purchase totals and related
refund/cleanup summaries share one statement snapshot. No source authority,
provider call, receipt creation or case opening occurs.

<!-- architecture-inventory
{"workflows":["annual-billing-support"],"workflowPurposes":["annual-billing-support=>Reads bounded annual purchase, recorded refund liability and agreement-stop evidence under current active-admin, explicitly opened same-company billing support-case and fresh-MFA authority; never adjudicates refunds or performs side effects."],"publicPackages":["talli_backend.modules.billing.public"],"routes":["/api/v1/billing/annual/support/purchases"],"ports":["AnnualSupportReadPersistence"],"adapterBindings":["AnnualSupportReadPersistence=>talli_backend.adapters.postgres_annual_support.PostgresAnnualSupportReadSession"],"adapterBindingOwners":["AnnualSupportReadPersistence=>backend-system"],"adapterBindingModes":["AnnualSupportReadPersistence=>verified active-admin opened billing support case; bounded consistent stored annual evidence across years, no provider or source-authority calls"]}
-->

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

<!-- architecture-inventory
{"workflows":["annual-refund-recovery"],"workflowPurposes":["annual-refund-recovery=>Authenticates the current owner to reconcile an already operation-bound request made by that actor; no allocation, source resolution or provider execution."],"publicPackages":["talli_backend.modules.billing.public"],"routes":["/api/v1/billing/annual/refund-recoveries"],"ports":["AnnualRefundRecoveryPersistence"],"adapterBindings":["AnnualRefundRecoveryPersistence=>talli_backend.adapters.postgres_annual_refund.PostgresAnnualRefundRecoverySession"],"adapterBindingOwners":["AnnualRefundRecoveryPersistence=>backend-system"],"adapterBindingModes":["AnnualRefundRecoveryPersistence=>verified current owner/fresh MFA at load and settlement; immutable request and original operation reconciliation only; provider absent by default, no source or claim binding"]}
-->


The existing owner read workflow also exposes
`/api/v1/billing/annual/refund-recovery-targets` through
`AnnualBillingReadPersistence.read_refund_recovery_targets`. The projection is
purchase-scoped and same-actor, owner/fresh-MFA authorized, source/provider free,
and read-only. It groups bound receipts by immutable refund operation order before
pagination and exposes no private source, provider, actor or monetary evidence.
Recovery independently authorizes and validates a selected receipt on explicit POST.

<!-- architecture-inventory
{"workflows":["annual-provider-notification-intake"],"workflowPurposes":["annual-provider-notification-intake=>Authenticates exact provider delivery bytes and commits immutable technical receipts; no actor, purchase resolution, provider call or financial mutation; injection absent by default."],"routes":["/api/v1/billing/annual/provider-notifications"],"technicalSchemas":["annual_notification_inbox"],"technicalTables":["annual_notification_inbox.receipts"],"technicalMigrations":["supabase/migrations/20260906204352_annual_notification_receipts.sql"],"ports":["AnnualNotificationAuthentication","AnnualNotificationPersistence"],"adapterBindings":["AnnualNotificationAuthentication=>talli_backend.adapters.vipps_webhook.VippsWebhookAuthentication","AnnualNotificationPersistence=>talli_backend.adapters.postgres_annual_notifications.PostgresAnnualNotificationInbox"],"adapterBindingOwners":["AnnualNotificationAuthentication=>backend-system","AnnualNotificationPersistence=>backend-system"],"adapterBindingModes":["AnnualNotificationAuthentication=>configured MT merchant HMAC authentication; no environment fallback or runtime activation","AnnualNotificationPersistence=>restricted actorless technical receipt insert/read only; no login grant, purchase lookup, financial write or worker"],"transportDependencies":["talli_backend.application.annual_notifications"]}
-->

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
