# Backend system boundary

<!-- architecture-inventory
{"adapterBindingModes":["SystemBoundaryTransport=>in-process FastAPI composition"],"adapterBindingOwners":["SystemBoundaryTransport=>backend-system"],"adapterBindings":["SystemBoundaryTransport=>talli_backend.main.create_app"],"adapterDependencies":[],"compositionRoots":["apps/backend/src/talli_backend/main.py"],"infrastructure":["durableWorker=>A durable worker consumes persisted delivery state outside the initiating transaction.","eventDelivery=>public.notification_outbox is the persisted event-delivery boundary.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"operationalAdapterRechecks":["true"],"operationalOwners":["backend-system"],"operationalReleaseDecisions":["deny-by-default"],"operationalTables":["public.launch_signoffs"],"ports":["SystemBoundaryTransport"],"publicPackages":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"routes":["/api/v1/company-access/cancellations","/api/v1/company-access/cancellations/{cancellation_id}/finalize","/api/v1/company-access/cancellations/{cancellation_id}/resume","/api/v1/company-access/cancellations/{cancellation_id}/reviews","/api/v1/company-access/context","/api/v1/company-access/invitation-side-effects/pending","/api/v1/company-access/invitation-side-effects/{operation_id}/complete","/api/v1/company-access/invitations","/api/v1/company-access/invitations/accept","/api/v1/company-access/invitations/lookup","/api/v1/company-access/invitations/{invitation_id}/resend","/api/v1/company-access/invitations/{invitation_id}/revoke","/api/v1/company-access/memberships","/api/v1/company-access/memberships/{user_id}","/api/v1/system-boundary/tracer"],"technicalMigrations":["supabase/migrations/0001_authenticated_workspace.sql","supabase/migrations/20260801090000_company_access_invitations.sql","supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql"],"technicalSchemas":["public"],"technicalStatements":["These tables implement idempotency, operational control, and event delivery only; they own no accounting, filing, billing, or authorization decision."],"technicalTables":["public.company_access_command_receipts","public.launch_signoffs","public.notification_outbox"],"transportDependencies":["__future__","collections","fastapi","fastapi.security","pydantic","re","starlette","talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public","talli_backend.openapi","typing","uuid"],"workflowDependencies":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"workflowPurposes":["company-access-administration=>Runs invitation, reviewer/read-only membership, cancellation, and deletion-review workflows atomically through the company_access public package.","company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"workflows":["company-access-administration","company-access-context","system-boundary-tracer"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["CompanyAccessGateway=>injected Supabase Auth and restricted Postgres adapter","CompanyRegistryGateway=>injected bounded HTTPS public-registry adapter"],"adapterBindingOwners":["CompanyAccessGateway=>backend-system","CompanyRegistryGateway=>backend-system"],"adapterBindings":["CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter","CompanyRegistryGateway=>talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter"],"adapterDependencies":["__future__","asyncio","base64","collections.abc","dataclasses","ipaddress","json","os","psycopg","psycopg.rows","re","talli_backend.modules.company_access.public","urllib.error","urllib.parse","urllib.request"],"ports":["CompanyAccessGateway","CompanyRegistryGateway"],"transportDependencies":["talli_backend.adapters.brreg_company_registry","talli_backend.adapters.supabase_company_access"]}
-->

<!-- architecture-inventory
{"routes":["/api/v1/company-access/agreements/reaccept","/api/v1/company-access/companies/{company_id}","/api/v1/company-access/onboarding","/api/v1/company-access/operator-companies","/api/v1/company-access/operator-context"],"technicalMigrations":["supabase/migrations/20260826100000_company_access_onboarding.sql"],"workflowPurposes":["company-access-onboarding-and-support=>Runs atomic company onboarding and agreement acceptance, accepted-member company lookup, and bounded support-operator context and company search through the company_access public package."],"workflows":["company-access-onboarding-and-support"]}
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
`/api/v1/company-access/operator-companies`. It keeps company creation and
agreement evidence atomic, exposes accepted-member company records, and confines
support lookup to the capability's verified operator policy. The composition
root injects `CompanyRegistryGateway` through
`talli_backend.adapters.brreg_company_registry.BrregCompanyRegistryAdapter`.

## Operational and technical ownership

The backend system owns the deny-by-default `public.launch_signoffs` operational
control state. It also owns `public.company_access_command_receipts` as technical
idempotency state and `public.notification_outbox` as technical event-delivery
state. These tables own no accounting, filing, billing, or authorization policy.
Their migrations are `supabase/migrations/0001_authenticated_workspace.sql` and
`supabase/migrations/20260801090000_company_access_invitations.sql`, extended by
`supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql`
and `supabase/migrations/20260826100000_company_access_onboarding.sql`.

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
