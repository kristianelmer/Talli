# Backend system boundary

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260827109000_ledger_opening_position_rebuild.sql"]}
-->

<!-- architecture-inventory
{"technicalMigrations":["supabase/migrations/20260828100000_banking_capability.sql"],"technicalTables":["backend_system.banking_migration_reconciliations","backend_system.banking_migration_runs","backend_system.banking_migration_source_rows"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["SystemBoundaryTransport=>in-process FastAPI composition"],"adapterBindingOwners":["SystemBoundaryTransport=>backend-system"],"adapterBindings":["SystemBoundaryTransport=>talli_backend.main.create_app"],"adapterDependencies":[],"compositionRoots":["apps/backend/src/talli_backend/main.py"],"infrastructure":["durableWorker=>A durable worker consumes persisted delivery state outside the initiating transaction.","eventDelivery=>public.notification_outbox is the persisted event-delivery boundary.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"operationalAdapterRechecks":["true"],"operationalOwners":["backend-system"],"operationalReleaseDecisions":["deny-by-default"],"operationalTables":["public.launch_signoffs"],"ports":["SystemBoundaryTransport"],"publicPackages":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"routes":["/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/context","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/system-boundary/tracer"],"technicalMigrations":["supabase/migrations/0001_authenticated_workspace.sql","supabase/migrations/20260801090000_company_access_invitations.sql","supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql"],"technicalSchemas":["backend_system","public"],"technicalStatements":["These tables implement idempotency, cursor signing, migration evidence, operational control, and event delivery only; they own no accounting, filing, billing, or authorization decision."],"technicalTables":["backend_system.ledger_command_receipts","backend_system.ledger_cursor_signing_keys","backend_system.ledger_migration_quarantine","backend_system.ledger_migration_reconciliations","backend_system.ledger_migration_runs","backend_system.ledger_migration_source_rows","backend_system.ledger_workflow_receipts","public.company_access_command_receipts","public.launch_signoffs","public.notification_outbox"],"transportDependencies":["__future__","collections","fastapi","fastapi.security","pydantic","re","starlette","talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public","talli_backend.openapi","typing","uuid"],"workflowDependencies":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"workflowPurposes":["company-access-administration=>Runs invitation, reviewer/read-only membership, cancellation, and deletion-review workflows atomically through the company_access public package.","company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"workflows":["company-access-administration","company-access-context","system-boundary-tracer"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["CompanyAccessGateway=>injected Supabase Auth and restricted Postgres adapter","CompanyRegistryGateway=>injected bounded HTTPS public-registry adapter"],"adapterBindingOwners":["CompanyAccessGateway=>backend-system","CompanyRegistryGateway=>backend-system"],"adapterBindings":["CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter","CompanyRegistryGateway=>talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter"],"adapterDependencies":["__future__","asyncio","base64","collections.abc","dataclasses","ipaddress","json","os","psycopg","psycopg.rows","re","talli_backend.modules.company_access.public","urllib.error","urllib.parse","urllib.request"],"ports":["CompanyAccessGateway","CompanyRegistryGateway"],"transportDependencies":["talli_backend.adapters.brreg_company_registry","talli_backend.adapters.supabase_company_access"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/company-access/agreements/reaccept","/api/v1/company-access/companies/{company_id}","/api/v1/company-access/company-year-admissions","/api/v1/company-access/company-year-admissions/{company_year_admission_id}/eligibility-rechecks","/api/v1/company-access/eligibility/definitive","/api/v1/company-access/eligibility/precheck","/api/v1/company-access/onboarding","/api/v1/company-access/operator-companies","/api/v1/company-access/operator-context"],"technicalMigrations":["supabase/migrations/20260826100000_company_access_onboarding.sql","supabase/migrations/20260826110000_company_year_admission.sql"],"workflowPurposes":["company-access-onboarding-and-support=>Retains the fail-closed legacy onboarding response, runs agreement reacceptance, accepted-member company lookup, and bounded support-operator context and company search through the company_access public package.","company-year-eligibility-and-admission=>Runs the public provisional company check, definitive manifest-owned interview, authenticated atomic company-year admission, and append-only post-admission safety rechecks through the company_access public package."],"workflows":["company-access-onboarding-and-support","company-year-eligibility-and-admission"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["LedgerPersistence=>request-scoped verified-actor restricted PostgreSQL adapter"],"adapterBindingOwners":["LedgerPersistence=>backend-system"],"adapterBindings":["LedgerPersistence=>talli_backend.adapters.supabase_ledger.SupabaseLedgerSession"],"adapterDependencies":["datetime","decimal","talli_backend.application.ledger_session","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.modules.ledger.service","talli_backend.shared.kernel"],"ports":["LedgerPersistence"],"publicPackages":["talli_backend.modules.ledger.public"],"routes":["/api/v1/ledger/administrative-costs","/api/v1/ledger/bank-suggestion-outcomes","/api/v1/ledger/company-year-close-assessment","/api/v1/ledger/corporate-decisions/finalizations","/api/v1/ledger/entries","/api/v1/ledger/investment-dividends","/api/v1/ledger/investment-purchases","/api/v1/ledger/investment-sales","/api/v1/ledger/manual-journals","/api/v1/ledger/opening-snapshots","/api/v1/ledger/owner-dividends/payments","/api/v1/ledger/period-locks","/api/v1/ledger/reconstruction-assessment","/api/v1/ledger/shareholder-loans","/api/v1/ledger/tax-settlements","/api/v1/new-year-starts"],"technicalMigrations":["supabase/migrations/20260827100000_ledger_capability.sql","supabase/migrations/20260827100500_ledger_writer_coordinators.sql","supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql","supabase/migrations/20260827103000_ledger_corrections.sql","supabase/migrations/20260827104000_ledger_company_year_close.sql"],"transportDependencies":["datetime","talli_backend.adapters.supabase_ledger","talli_backend.application.ledger_workflow","talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public","talli_backend.shared.kernel"],"workflowDependencies":["talli_backend.application.opening_snapshot_compatibility","talli_backend.modules.ledger.public"],"workflowPurposes":["ledger-posting-and-period-control=>Authenticates one verified actor and runs intent-specific narrow-ledger posting, immutable source-owned full-year reconstruction and company-year close assessment, cross-capability writer coordination, deterministic cursor queries, the frozen opening-snapshot compatibility read, and compatibility locking without changing a future capability contract."],"workflows":["ledger-posting-and-period-control"]}
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
`/api/v1/company-access/operator-context`, and
`/api/v1/company-access/operator-companies`. Its deprecated onboarding route
fails closed and cannot create a company; the workflow otherwise exposes
agreement reacceptance and accepted-member company records, and confines
support lookup to the capability's verified operator policy. The composition
root injects `CompanyRegistryGateway` through
`talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter`.

The `new-year-start` workflow serves `/api/v1/new-year-starts` and coordinates
`talli_backend.modules.ledger.public` with the frozen
`talli_backend.modules.shareholder_register_filing.public` contract in one
backend-owned transaction. The shareholder-register module owns no migrated
data or filing behavior until #151. The application-layer compatibility adapter
translates both intents only inside this workflow's active transaction.

The `ledger-posting-and-period-control` workflow serves `/api/v1/ledger/entries`,
`/api/v1/ledger/opening-snapshots`, `/api/v1/ledger/period-locks`,
`/api/v1/ledger/company-year-close-assessment`,
`/api/v1/ledger/reconstruction-assessment`,
`/api/v1/ledger/administrative-costs`, `/api/v1/ledger/investment-dividends`,
`/api/v1/ledger/shareholder-loans`, `/api/v1/ledger/tax-settlements`,
`/api/v1/ledger/bank-suggestion-outcomes`,
`/api/v1/ledger/investment-purchases`, `/api/v1/ledger/investment-sales`,
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

## Operational and technical ownership

The banking expand stage adds immutable technical migration evidence in
`backend_system.banking_migration_runs`,
`backend_system.banking_migration_source_rows`, and
`backend_system.banking_migration_reconciliations`. These records prove the
exact-ID, count, and canonical-hash transfer performed by
`supabase/migrations/20260828100000_banking_capability.sql`; they contain no
banking classification or accounting policy.

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

## Allowed dependencies and change rule

Transport, workflow, and adapter dependency allowlists are in the system
manifest. Adding a workflow, technical table, binding, or dependency changes
this document and `backend-system.json` together, with an ADR review.
