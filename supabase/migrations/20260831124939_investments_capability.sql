-- Canonical investments capability expand migration (issue #141).

begin;

do $block$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'investments_store_owner') then
    create role investments_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'investments_executor') then
    create role investments_executor nologin noinherit nobypassrls;
  end if;
end
$block$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:purchase-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;

alter role investments_store_owner nologin noinherit nobypassrls;
alter role investments_executor nologin noinherit nobypassrls;

do $block$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, company_access_executor to %I',
    current_user
  );
end
$block$;

create schema if not exists investments authorization investments_store_owner;
revoke all on schema investments from public, anon, authenticated, service_role;
grant usage on schema investments to investments_executor;

do $investments_backend_membership$
begin
  if exists (
    select 1 from pg_catalog.pg_roles where rolname = 'talli_ledger_backend'
  ) then
    grant investments_executor to talli_ledger_backend
      with inherit false, set true;
  end if;
end
$investments_backend_membership$;

create table investments.positions (
  id uuid primary key default extensions.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  investment_key text not null check (pg_catalog.btrim(investment_key) <> ''),
  name text not null check (pg_catalog.btrim(name) <> ''),
  kind text not null check (kind = 'norwegian_private_company'),
  tax_treatment text not null check (tax_treatment = 'fritaksmetoden'),
  org_number text check (org_number is null or org_number ~ '^[0-9]{9}$'),
  share_count bigint not null check (share_count >= 0),
  cost_basis numeric(20, 2) not null check (cost_basis >= 0),
  movements jsonb not null default '[]'::jsonb,
  lot_history_status text not null check (
    lot_history_status in ('complete', 'needs_reconstruction')
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  updated_at timestamptz not null default pg_catalog.now(),
  unique (company_id, investment_key)
);

create table investments.acquisition_lots (
  id uuid primary key default extensions.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references investments.positions(id) on delete restrict,
  acquisition_action_id uuid not null,
  acquisition_date date not null,
  original_share_count bigint not null check (original_share_count > 0),
  remaining_share_count bigint not null check (
    remaining_share_count >= 0 and remaining_share_count <= original_share_count
  ),
  original_cost_basis numeric(20, 2) not null check (original_cost_basis > 0),
  remaining_cost_basis numeric(20, 2) not null check (
    remaining_cost_basis >= 0 and remaining_cost_basis <= original_cost_basis
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  unique (acquisition_action_id),
  check (remaining_share_count <> 0 or remaining_cost_basis = 0)
);

do $block$
begin
  if exists (
    select 1
    from public.investment_positions position
    where position.share_count <> pg_catalog.trunc(position.share_count)
  ) then
    raise exception 'investments_migration_fractional_share_count';
  end if;
end
$block$;

insert into investments.positions (
  id, company_id, investment_key, name, kind, tax_treatment, org_number,
  share_count, cost_basis, movements, lot_history_status,
  created_by, created_at, updated_at
)
select
  position.id, position.company_id, position.investment_key, position.name,
  position.kind, position.tax_treatment, position.org_number,
  position.share_count::bigint, position.cost_basis, position.movements,
  position.lot_history_status, position.created_by,
  position.created_at, position.updated_at
from public.investment_positions position;

insert into investments.acquisition_lots (
  id, company_id, position_id, acquisition_action_id, acquisition_date,
  original_share_count, remaining_share_count, original_cost_basis,
  remaining_cost_basis, created_by, created_at
)
select
  lot.id, lot.company_id, lot.position_id, lot.acquisition_action_id,
  lot.acquisition_date, lot.original_share_count, lot.remaining_share_count,
  lot.original_cost_basis, lot.remaining_cost_basis,
  lot.created_by, lot.created_at
from public.investment_lots lot;

create index investments_positions_company_id_idx
  on investments.positions(company_id);
create index investments_acquisition_lots_company_id_idx
  on investments.acquisition_lots(company_id);
create index investments_acquisition_lots_fifo_idx
  on investments.acquisition_lots(position_id, acquisition_date, id);

alter table investments.positions owner to investments_store_owner;
alter table investments.acquisition_lots owner to investments_store_owner;

alter table investments.positions enable row level security;
alter table investments.positions force row level security;
alter table investments.acquisition_lots enable row level security;
alter table investments.acquisition_lots force row level security;

create policy investments_positions_member_select
on investments.positions for select to investments_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_positions_owner_insert
on investments.positions for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_positions_owner_update
on investments.positions for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_acquisition_lots_member_select
on investments.acquisition_lots for select to investments_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_acquisition_lots_owner_insert
on investments.acquisition_lots for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

grant select on investments.positions, investments.acquisition_lots
  to investments_executor;
grant select, insert, update on investments.positions
  to investments_store_owner;
grant select, insert on investments.acquisition_lots
  to investments_store_owner;
grant execute on function public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid)
to investments_executor, investments_store_owner;

revoke all on investments.positions, investments.acquisition_lots
from public, anon, authenticated, service_role;

do $block$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, company_access_executor from %I',
    current_user
  );
end
$block$;

commit;
