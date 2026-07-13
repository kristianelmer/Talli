-- Seal every source used by the RF-1086 production release decision while one
-- short-lived provider operation is in flight. The lease is service-only and
-- expires after 120 seconds so a crashed worker cannot freeze customer data.
create table public.rf1086_production_leases (
  preview_id uuid primary key references public.filing_previews(id) on delete cascade,
  lease_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  actor_id uuid not null,
  acquired_at timestamptz not null,
  expires_at timestamptz not null,
  released_at timestamptz,
  check (expires_at = acquired_at + interval '120 seconds'),
  check (released_at is null or released_at >= acquired_at)
);

create index rf1086_production_leases_active_company_period_idx
on public.rf1086_production_leases(company_id, income_year, expires_at)
where released_at is null;

create index rf1086_production_leases_active_actor_idx
on public.rf1086_production_leases(actor_id, expires_at)
where released_at is null;

alter table public.rf1086_production_leases enable row level security;
revoke all on public.rf1086_production_leases from public, anon, authenticated, service_role;

create or replace function private.acquire_rf1086_production_lease(
  p_preview_id uuid,
  p_actor_id uuid
)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  preview_company_id uuid;
  preview_income_year integer;
  preview_filing text;
  preview_status text;
  acquired_at_value timestamptz := statement_timestamp();
  lease_id_value uuid := gen_random_uuid();
  affected_rows integer;
begin
  if p_preview_id is null or p_actor_id is null then
    raise exception 'RF-1086 production lease input is invalid.' using errcode = '22023';
  end if;

  select preview.company_id, preview.income_year, preview.filing, preview.status
  into preview_company_id, preview_income_year, preview_filing, preview_status
  from public.filing_previews preview
  where preview.id = p_preview_id
  for key share;

  if not found
    or preview_filing <> 'aksjonærregisteroppgaven'
    or preview_status <> 'ready'
    or not exists (
      select 1
      from public.company_memberships membership
      where membership.company_id = preview_company_id
        and membership.user_id = p_actor_id
        and membership.role = 'owner'
        and membership.accepted_at is not null
    )
  then
    raise exception 'RF-1086 production lease is not authorized.' using errcode = '42501';
  end if;

  delete from public.rf1086_production_leases lease
  where lease.preview_id = p_preview_id
    and (lease.released_at is not null or lease.expires_at <= acquired_at_value);

  insert into public.rf1086_production_leases (
    preview_id,
    lease_id,
    company_id,
    income_year,
    actor_id,
    acquired_at,
    expires_at
  ) values (
    p_preview_id,
    lease_id_value,
    preview_company_id,
    preview_income_year,
    p_actor_id,
    acquired_at_value,
    acquired_at_value + interval '120 seconds'
  )
  on conflict (preview_id) do nothing;

  get diagnostics affected_rows = row_count;
  if affected_rows <> 1 then
    raise sqlstate 'PT409' using message = 'RF-1086 production lease conflict.';
  end if;

  return lease_id_value;
end;
$$;

create or replace function private.release_rf1086_production_lease(
  p_preview_id uuid,
  p_lease_id uuid
)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  affected_rows integer;
begin
  if p_preview_id is null or p_lease_id is null then
    raise exception 'RF-1086 production lease input is invalid.' using errcode = '22023';
  end if;

  update public.rf1086_production_leases lease
  set released_at = statement_timestamp()
  where lease.preview_id = p_preview_id
    and lease.lease_id = p_lease_id
    and lease.released_at is null;

  get diagnostics affected_rows = row_count;
  return affected_rows = 1;
end;
$$;

create or replace function private.rf1086_active_company_period_lease(
  p_company_id uuid,
  p_income_year integer
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.rf1086_production_leases lease
    where lease.company_id = p_company_id
      and lease.income_year = p_income_year
      and lease.released_at is null
      and lease.expires_at > statement_timestamp()
  );
$$;

create or replace function private.rf1086_active_company_lease(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.rf1086_production_leases lease
    where lease.company_id = p_company_id
      and lease.released_at is null
      and lease.expires_at > statement_timestamp()
  );
$$;

create or replace function private.rf1086_active_actor_lease(p_actor_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.rf1086_production_leases lease
    where lease.actor_id = p_actor_id
      and lease.released_at is null
      and lease.expires_at > statement_timestamp()
  );
$$;

create or replace function private.block_rf1086_company_period_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  old_row jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) else null end;
  new_row jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) else null end;
begin
  if (old_row is not null and private.rf1086_active_company_period_lease(
      (old_row ->> 'company_id')::uuid,
      (old_row ->> 'income_year')::integer
    )) or (new_row is not null and private.rf1086_active_company_period_lease(
      (new_row ->> 'company_id')::uuid,
      (new_row ->> 'income_year')::integer
    ))
  then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.block_rf1086_company_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  old_row jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) else null end;
  new_row jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) else null end;
begin
  if (old_row is not null and private.rf1086_active_company_lease((old_row ->> 'company_id')::uuid))
    or (new_row is not null and private.rf1086_active_company_lease((new_row ->> 'company_id')::uuid))
  then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.block_rf1086_company_row_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  old_id uuid := case when tg_op in ('UPDATE', 'DELETE') then old.id else null end;
  new_id uuid := case when tg_op in ('INSERT', 'UPDATE') then new.id else null end;
begin
  if (old_id is not null and private.rf1086_active_company_lease(old_id))
    or (new_id is not null and private.rf1086_active_company_lease(new_id))
  then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.block_rf1086_preview_comment_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  old_row jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) else null end;
  new_row jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) else null end;
begin
  if exists (
    select 1
    from public.rf1086_production_leases lease
    where lease.released_at is null
      and lease.expires_at > statement_timestamp()
      and (
        (old_row is not null
          and lease.company_id = (old_row ->> 'company_id')::uuid
          and lease.preview_id = (old_row ->> 'preview_id')::uuid)
        or (new_row is not null
          and lease.company_id = (new_row ->> 'company_id')::uuid
          and lease.preview_id = (new_row ->> 'preview_id')::uuid)
      )
  ) then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.block_rf1086_actor_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  old_row jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) else null end;
  new_row jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) else null end;
begin
  if (old_row is not null and private.rf1086_active_actor_lease((old_row ->> 'actor_id')::uuid))
    or (new_row is not null and private.rf1086_active_actor_lease((new_row ->> 'actor_id')::uuid))
  then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.block_rf1086_launch_signoff_gate_mutation()
returns trigger
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if (tg_op in ('UPDATE', 'DELETE') and old.key = 'rf1086_authority'
      or tg_op in ('INSERT', 'UPDATE') and new.key = 'rf1086_authority')
    and exists (
      select 1
      from public.rf1086_production_leases lease
      where lease.released_at is null
        and lease.expires_at > statement_timestamp()
    )
  then
    raise exception 'RF-1086 production release is temporarily sealed.' using errcode = '55000';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

drop trigger if exists seal_rf1086_companies on public.companies;
create trigger seal_rf1086_companies before insert or update or delete on public.companies
for each row execute function private.block_rf1086_company_row_gate_mutation();

drop trigger if exists seal_rf1086_company_memberships on public.company_memberships;
create trigger seal_rf1086_company_memberships before insert or update or delete on public.company_memberships
for each row execute function private.block_rf1086_company_gate_mutation();

drop trigger if exists seal_rf1086_opening_balance_setups on public.opening_balance_setups;
create trigger seal_rf1086_opening_balance_setups before insert or update or delete on public.opening_balance_setups
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_ledger_entries on public.ledger_entries;
create trigger seal_rf1086_ledger_entries before insert or update or delete on public.ledger_entries
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_holding_actions on public.holding_actions;
create trigger seal_rf1086_holding_actions before insert or update or delete on public.holding_actions
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_bank_transactions on public.bank_transactions;
create trigger seal_rf1086_bank_transactions before insert or update or delete on public.bank_transactions
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_documents on public.documents;
create trigger seal_rf1086_documents before insert or update or delete on public.documents
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_filing_overrides on public.filing_overrides;
create trigger seal_rf1086_filing_overrides before insert or update or delete on public.filing_overrides
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_period_locks on public.period_locks;
create trigger seal_rf1086_period_locks before insert or update or delete on public.period_locks
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_annual_data on public.annual_data;
create trigger seal_rf1086_annual_data before insert or update or delete on public.annual_data
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_filing_previews on public.filing_previews;
create trigger seal_rf1086_filing_previews before insert or update or delete on public.filing_previews
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_filing_submissions on public.filing_submissions;
create trigger seal_rf1086_filing_submissions before insert or update or delete on public.filing_submissions
for each row execute function private.block_rf1086_company_period_gate_mutation();

drop trigger if exists seal_rf1086_billing_accounts on public.billing_accounts;
create trigger seal_rf1086_billing_accounts before insert or update or delete on public.billing_accounts
for each row execute function private.block_rf1086_company_gate_mutation();

drop trigger if exists seal_rf1086_authority_permissions on public.authority_permissions;
create trigger seal_rf1086_authority_permissions before insert or update or delete on public.authority_permissions
for each row execute function private.block_rf1086_company_gate_mutation();

drop trigger if exists seal_rf1086_authority_test_runs on public.authority_test_runs;
create trigger seal_rf1086_authority_test_runs before insert or update or delete on public.authority_test_runs
for each row execute function private.block_rf1086_company_gate_mutation();

drop trigger if exists seal_rf1086_filing_review_comments on public.filing_review_comments;
create trigger seal_rf1086_filing_review_comments before insert or update or delete on public.filing_review_comments
for each row execute function private.block_rf1086_preview_comment_gate_mutation();

drop trigger if exists seal_rf1086_step_up_events on public.step_up_events;
create trigger seal_rf1086_step_up_events before insert or update or delete on public.step_up_events
for each row execute function private.block_rf1086_actor_gate_mutation();

drop trigger if exists seal_rf1086_production_security_grants on public.production_security_grants;
create trigger seal_rf1086_production_security_grants before insert or update or delete on public.production_security_grants
for each row execute function private.block_rf1086_actor_gate_mutation();

drop trigger if exists seal_rf1086_launch_signoffs on public.launch_signoffs;
create trigger seal_rf1086_launch_signoffs before insert or update or delete on public.launch_signoffs
for each row execute function private.block_rf1086_launch_signoff_gate_mutation();

revoke all on function private.acquire_rf1086_production_lease(uuid, uuid) from public, anon, authenticated, service_role;
revoke all on function private.release_rf1086_production_lease(uuid, uuid) from public, anon, authenticated, service_role;
revoke all on function private.rf1086_active_company_period_lease(uuid, integer) from public, anon, authenticated, service_role;
revoke all on function private.rf1086_active_company_lease(uuid) from public, anon, authenticated, service_role;
revoke all on function private.rf1086_active_actor_lease(uuid) from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_company_period_gate_mutation() from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_company_gate_mutation() from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_company_row_gate_mutation() from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_preview_comment_gate_mutation() from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_actor_gate_mutation() from public, anon, authenticated, service_role;
revoke all on function private.block_rf1086_launch_signoff_gate_mutation() from public, anon, authenticated, service_role;

grant usage on schema private to service_role;
grant execute on function private.acquire_rf1086_production_lease(uuid, uuid) to service_role;
grant execute on function private.release_rf1086_production_lease(uuid, uuid) to service_role;

create or replace function public.acquire_rf1086_production_lease(
  p_preview_id uuid,
  p_actor_id uuid
)
returns uuid
language sql
volatile
security invoker
set search_path = ''
as $$
  select private.acquire_rf1086_production_lease(p_preview_id, p_actor_id);
$$;

create or replace function public.release_rf1086_production_lease(
  p_preview_id uuid,
  p_lease_id uuid
)
returns boolean
language sql
volatile
security invoker
set search_path = ''
as $$
  select private.release_rf1086_production_lease(p_preview_id, p_lease_id);
$$;

revoke all on function public.acquire_rf1086_production_lease(uuid, uuid) from public, anon, authenticated;
revoke all on function public.release_rf1086_production_lease(uuid, uuid) from public, anon, authenticated;
grant execute on function public.acquire_rf1086_production_lease(uuid, uuid) to service_role;
grant execute on function public.release_rf1086_production_lease(uuid, uuid) to service_role;
