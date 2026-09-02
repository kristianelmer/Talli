-- Give canonical FIFO allocations the stable identity required by owned exports.

begin;

do $investments_allocation_identity_membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I', current_user
  );
end
$investments_allocation_identity_membership$;

select pg_catalog.set_config(
  'talli.investments_allocation_identity_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
do $investments_allocation_identity_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting(
      'talli.investments_allocation_identity_migration_principal'
    )
  );
end
$investments_allocation_identity_schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:stage-exit:v1', 0)
);
lock table public.investment_lot_allocations in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;

alter table investments.share_sale_allocations add column id uuid;

update investments.share_sale_allocations canonical
set id = legacy.id
from public.investment_lot_allocations legacy
where legacy.sale_action_id = canonical.sale_action_id
  and legacy.lot_id = canonical.acquisition_lot_id;

do $investments_allocation_identity_reconciliation$
begin
  if exists (
    select 1 from investments.share_sale_allocations where id is null
  ) then raise exception 'investments_allocation_identity_reconciliation_failed'; end if;
end
$investments_allocation_identity_reconciliation$;

alter table investments.share_sale_allocations
  alter column id set default extensions.gen_random_uuid(),
  alter column id set not null;
alter table investments.share_sale_allocations
  add constraint investments_share_sale_allocations_id_key unique (id);

create or replace function backend_system.align_legacy_share_sale_allocation_id_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
declare
  v_id uuid;
begin
  select allocation.id into v_id
  from investments.share_sale_allocations allocation
  where allocation.sale_action_id = new.sale_action_id
    and allocation.acquisition_lot_id = new.lot_id;
  if v_id is not null then new.id := v_id; end if;
  return new;
end;
$function$;

create or replace function backend_system.sync_legacy_share_sale_allocation_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
declare
  v_lot investments.acquisition_lots%rowtype;
  v_order integer;
begin
  select lot.* into v_lot from investments.acquisition_lots lot
  where lot.id = new.lot_id;
  if not found then raise exception 'investments_dependency_unavailable'; end if;
  select count(*)::integer + 1 into v_order
  from investments.share_sale_allocations allocation
  where allocation.sale_action_id = new.sale_action_id;
  insert into investments.share_sale_allocations (
    id, sale_action_id, company_id, position_id, acquisition_lot_id,
    allocation_order, acquisition_date, allocated_share_count,
    allocated_cost_basis, created_by, created_at
  ) values (
    new.id, new.sale_action_id, new.company_id, new.position_id, new.lot_id,
    v_order, v_lot.acquisition_date, new.allocated_share_count,
    new.allocated_cost_basis, new.created_by, new.created_at
  ) on conflict (sale_action_id, acquisition_lot_id) do nothing;
  return new;
end;
$function$;

alter function backend_system.align_legacy_share_sale_allocation_id_v1()
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_share_sale_allocation_v1()
  owner to ledger_store_owner;
revoke all on function
  backend_system.align_legacy_share_sale_allocation_id_v1(),
  backend_system.sync_legacy_share_sale_allocation_v1()
from public, anon, authenticated, service_role,
  investments_executor, investments_workflow_executor, talli_ledger_backend;

drop trigger if exists align_legacy_share_sale_allocation_id
  on public.investment_lot_allocations;
create trigger align_legacy_share_sale_allocation_id
before insert on public.investment_lot_allocations
for each row execute function
  backend_system.align_legacy_share_sale_allocation_id_v1();

set local role ledger_store_owner;
do $investments_allocation_identity_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting(
      'talli.investments_allocation_identity_migration_principal'
    )
  );
end
$investments_allocation_identity_schema_authority_revoke$;
revoke create on schema backend_system from ledger_store_owner;
reset role;

do $investments_allocation_identity_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I', current_user
  );
end
$investments_allocation_identity_revoke$;

commit;
