create table if not exists public.authority_operations (
  id uuid primary key default gen_random_uuid(),
  operation text not null check (operation in ('register_rf1086_system')),
  actor_id uuid not null references auth.users(id) on delete restrict,
  status text not null check (status in ('started', 'succeeded', 'failed', 'conflict')),
  request_hash text not null check (request_hash ~ '^[a-f0-9]{64}$'),
  result_code text not null default 'started' check (result_code in (
    'started',
    'created_and_verified',
    'already_verified',
    'definition_conflict',
    'authority_token_error',
    'authority_network_error',
    'authority_http_error',
    'authority_response_invalid',
    'authority_operation_failed'
  )),
  authority_http_status integer check (authority_http_status between 100 and 599),
  metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(metadata) = 'object'
    and metadata - array['systemId', 'clientId', 'right'] = '{}'::jsonb
  ),
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  check (
    (status = 'started' and completed_at is null)
    or (status <> 'started' and completed_at is not null)
  )
);

create index if not exists authority_operations_created_at_idx
on public.authority_operations(created_at desc);

create index if not exists authority_operations_actor_id_idx
on public.authority_operations(actor_id, created_at desc);

alter table public.authority_operations enable row level security;

revoke all on table public.authority_operations from public, anon, authenticated;
revoke all on table public.authority_operations from service_role;
grant select on table public.authority_operations to authenticated;
grant select on table public.authority_operations to service_role;
grant insert, update on table public.authority_operations to service_role;

drop policy if exists "active admin operators read authority operations"
on public.authority_operations;

create policy "active admin operators read authority operations"
on public.authority_operations for select
to authenticated
using (
  exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.role = 'admin'
      and o.active
  )
);
