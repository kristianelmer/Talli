# Backend system boundary

## Purpose

`backend-system.json` is the source of truth for backend composition that no
business capability can own: named workflows, operational control state,
technical persistence, durable infrastructure, and adapter bindings.

## Workflow and public package

The `system-boundary-tracer` workflow serves
`/api/v1/system-boundary/tracer` and may call only
`talli_backend.modules.system_boundary.public`. `main.py` is the single FastAPI
composition root; it does not become a business capability.

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
