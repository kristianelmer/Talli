# Backend system boundary

<!-- architecture-inventory
{"adapterBindingModes":["SystemBoundaryTransport=>in-process FastAPI composition"],"adapterBindingOwners":["SystemBoundaryTransport=>backend-system"],"adapterBindings":["SystemBoundaryTransport=>talli_backend.main.create_app"],"adapterDependencies":[],"compositionRoots":["apps/backend/src/talli_backend/main.py"],"infrastructure":["durableWorker=>A durable worker consumes persisted delivery state outside the initiating transaction.","eventDelivery=>public.notification_outbox is the persisted event-delivery boundary.","idempotency=>Durable idempotency records are required for consequential commands before provider I/O.","migrationRunner=>Supabase migrations in supabase/migrations are applied by the deployment migration runner.","transactions=>Short Postgres transactions owned by backend application workflows."],"operationalAdapterRechecks":["true"],"operationalOwners":["backend-system"],"operationalReleaseDecisions":["deny-by-default"],"operationalTables":["public.launch_signoffs"],"ports":["SystemBoundaryTransport"],"publicPackages":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"routes":["/api/v1/company-access/context","/api/v1/system-boundary/tracer"],"technicalMigrations":["supabase/migrations/0001_authenticated_workspace.sql"],"technicalSchemas":["public"],"technicalStatements":["These tables implement operational control and event delivery only; they own no accounting, filing, billing, or authorization decision."],"technicalTables":["public.launch_signoffs","public.notification_outbox"],"transportDependencies":["__future__","collections","fastapi","fastapi.security","pydantic","re","starlette","talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public","talli_backend.openapi","typing","uuid"],"workflowDependencies":["talli_backend.modules.company_access.public","talli_backend.modules.system_boundary.public"],"workflowPurposes":["company-access-context=>Returns the authenticated, policy-authorized selected company context through FastAPI.","system-boundary-tracer=>Returns a deterministic availability response from the independently deployable FastAPI boundary."],"workflows":["company-access-context","system-boundary-tracer"]}
-->

<!-- architecture-inventory
{"adapterBindingModes":["CompanyAccessGateway=>injected Supabase Auth and PostgREST adapter"],"adapterBindingOwners":["CompanyAccessGateway=>backend-system"],"adapterBindings":["CompanyAccessGateway=>talli_backend.adapters.supabase_company_access.SupabaseCompanyAccessAdapter"],"adapterDependencies":["__future__","asyncio","collections.abc","dataclasses","ipaddress","json","os","talli_backend.modules.company_access.public","urllib.error","urllib.parse","urllib.request"],"ports":["CompanyAccessGateway"],"transportDependencies":["talli_backend.adapters.supabase_company_access"]}
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

## Operational and technical ownership

The backend system owns the deny-by-default `public.launch_signoffs` operational
control state. It also owns `public.notification_outbox` as technical
event-delivery state. Neither table owns accounting, filing, billing, or
authorization policy. Their current migration is
`supabase/migrations/0001_authenticated_workspace.sql`.

## Infrastructure and adapters

Named application workflows use short transactions. Consequential external
operations require durable idempotency before provider I/O, and persisted
`eventDelivery` state is consumed outside the initiating transaction. The
`migrationRunner` owns `supabase/migrations`; a `durableWorker` owns delivery
processing. `SystemBoundaryTransport` is bound only to
`talli_backend.main.create_app`.

## Allowed dependencies and change rule

Transport, workflow, and adapter dependency allowlists are in the system
manifest. Adding a workflow, technical table, binding, or dependency changes
this document and `backend-system.json` together, with an ADR review.
