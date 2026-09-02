-- Canonical investments share-sale and FIFO workflow (issue #142).
-- The predecessor coordinator remains available during deployment overlap and
-- is removed only by the separately rehearsed contract release artifact.

begin;

-- Supabase's migration principal is deliberately not a persistent member of
-- the storage-owner roles. Borrow the same bounded memberships as the purchase
-- workflow so locks and schema changes work in the hosted migrator, then revoke
-- them before commit.
do $investments_sale_migration_membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner to %I',
    current_user
  );
end
$investments_sale_migration_membership$;

select pg_catalog.set_config(
  'talli.investments_sale_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema ledger, backend_system to ledger_store_owner;
do $investments_sale_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema ledger, backend_system to %I',
    pg_catalog.current_setting('talli.investments_sale_migration_principal')
  );
end
$investments_sale_schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:sale-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.investment_lot_allocations in share row exclusive mode;
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;

-- PostgreSQL treats LEAST as syntax rather than a schema-owned function. Repair
-- the predecessor capsule before overlap traffic can reach it; the historical
-- migration schema-qualified LEAST and therefore failed on PostgreSQL 17.
do $investments_sale_repair_predecessor$
declare
  v_definition text;
begin
  select pg_catalog.pg_get_functiondef(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'::regprocedure
  ) into v_definition;
  if pg_catalog.strpos(
    v_definition,
    'pg_catalog.least(v_left, v_lot.remaining_share_count)'
  ) > 0 then
    execute pg_catalog.replace(
      v_definition,
      'pg_catalog.least(v_left, v_lot.remaining_share_count)',
      'case when v_left < v_lot.remaining_share_count then v_left '
        || 'else v_lot.remaining_share_count end'
    );
  end if;
end
$investments_sale_repair_predecessor$;

create table investments.share_sales (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text,
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  position_id uuid not null references investments.positions(id) on delete restrict,
  accounting_entry_id uuid unique,
  legacy_imported boolean not null default false,
  sale_date date not null,
  sold_share_count bigint not null check (sold_share_count > 0),
  proceeds numeric(20, 2) not null check (proceeds > 0),
  fifo_cost_basis_reduction numeric(20, 2) not null check (
    fifo_cost_basis_reduction >= 0
  ),
  gain_or_loss numeric(20, 2) not null,
  remaining_share_count bigint not null check (remaining_share_count >= 0),
  remaining_cost_basis numeric(20, 2) not null check (remaining_cost_basis >= 0),
  bank_transaction_id uuid,
  document_id uuid,
  document_status text not null check (
    document_status in ('attached', 'missing_accepted_warning', 'not_required')
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  completed_at timestamptz,
  check (
    (accounting_entry_id is null and completed_at is null)
    or (accounting_entry_id is not null and completed_at is not null)
  ),
  unique (created_by, company_id, idempotency_key)
);

create table investments.share_sale_allocations (
  sale_action_id uuid not null references investments.share_sales(action_id)
    on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references investments.positions(id) on delete restrict,
  acquisition_lot_id uuid not null references investments.acquisition_lots(id)
    on delete restrict,
  allocation_order integer not null check (allocation_order > 0),
  acquisition_date date not null,
  allocated_share_count bigint not null check (allocated_share_count > 0),
  allocated_cost_basis numeric(20, 2) not null check (allocated_cost_basis >= 0),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  primary key (sale_action_id, acquisition_lot_id),
  unique (sale_action_id, allocation_order)
);

insert into investments.share_sales (
  action_id, company_id, income_year, idempotency_key, request_fingerprint,
  position_id, accounting_entry_id, legacy_imported,
  sale_date, sold_share_count, proceeds, fifo_cost_basis_reduction,
  gain_or_loss, remaining_share_count, remaining_cost_basis,
  bank_transaction_id, document_id, document_status,
  created_by, created_at, completed_at
)
select
  action.id, action.company_id, action.income_year, null,
  pg_catalog.encode(extensions.digest(action.payload::text, 'sha256'), 'hex'),
  (action.payload ->> 'position_id')::uuid,
  action.ledger_entry_id, true,
  coalesce((action.payload ->> 'sale_date')::date, action.action_date),
  (action.payload ->> 'sold_share_count')::bigint,
  (action.payload ->> 'proceeds')::numeric,
  (action.payload ->> 'cost_basis_reduction')::numeric,
  (action.payload ->> 'gain_or_loss')::numeric,
  (action.payload ->> 'remaining_share_count')::bigint,
  (action.payload ->> 'remaining_cost_basis')::numeric,
  action.bank_transaction_id, action.document_id,
  coalesce(action.payload ->> 'document_status', 'not_required'),
  action.created_by, action.created_at,
  case when action.ledger_entry_id is null then null else action.created_at end
from public.holding_actions action
where action.action_type = 'share_sale';

insert into investments.share_sale_allocations (
  sale_action_id, company_id, position_id, acquisition_lot_id,
  allocation_order, acquisition_date, allocated_share_count,
  allocated_cost_basis, created_by, created_at
)
select
  allocation.sale_action_id, allocation.company_id, allocation.position_id,
  allocation.lot_id,
  row_number() over (
    partition by allocation.sale_action_id
    order by lot.acquisition_date, lot.id
  )::integer,
  lot.acquisition_date, allocation.allocated_share_count,
  allocation.allocated_cost_basis, allocation.created_by,
  allocation.created_at
from public.investment_lot_allocations allocation
join public.investment_lots lot on lot.id = allocation.lot_id
join investments.share_sales sale on sale.action_id = allocation.sale_action_id;

create index investments_share_sales_company_year_idx
  on investments.share_sales(company_id, income_year, sale_date, action_id);
create index investments_share_sale_allocations_position_idx
  on investments.share_sale_allocations(position_id, sale_action_id);

alter table investments.share_sales owner to investments_store_owner;
alter table investments.share_sale_allocations owner to investments_store_owner;
alter table investments.share_sales enable row level security;
alter table investments.share_sales force row level security;
alter table investments.share_sale_allocations enable row level security;
alter table investments.share_sale_allocations force row level security;

create policy investments_share_sales_member_select
on investments.share_sales for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_share_sales_owner_insert
on investments.share_sales for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_share_sales_owner_update
on investments.share_sales for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_share_sale_allocations_member_select
on investments.share_sale_allocations for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_share_sale_allocations_owner_insert
on investments.share_sale_allocations for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_lots_sale_workflow_update
on investments.acquisition_lots for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function investments.share_sale_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(p_request::text, 'sha256'), 'hex');
$function$;

create or replace function investments.get_share_sale_replay_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_sale investments.share_sales%rowtype;
  v_fingerprint text := investments.share_sale_fingerprint_v1(p_request);
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-sale:' ||
      coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select sale.* into v_sale
  from investments.share_sales sale
  where sale.action_id = (p_request ->> 'actionId')::uuid
     or (
       sale.created_by = v_actor_id
       and sale.company_id = (p_request ->> 'companyId')::uuid
       and sale.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (sale.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (
      not v_sale.legacy_imported
      and v_sale.request_fingerprint <> v_fingerprint
    )
    or v_sale.company_id <> (p_request ->> 'companyId')::uuid
    or v_sale.income_year <> (p_request ->> 'incomeYear')::integer
    or v_sale.position_id <> (p_request ->> 'positionId')::uuid
    or v_sale.sale_date <> (p_request ->> 'saleDate')::date
    or v_sale.sold_share_count <> (p_request ->> 'soldShareCount')::bigint
    or v_sale.proceeds <> (p_request ->> 'proceeds')::numeric
    or v_sale.bank_transaction_id is distinct from
      nullif(p_request ->> 'bankTransactionId', '')::uuid
    or v_sale.document_id is distinct from
      nullif(p_request ->> 'documentId', '')::uuid
    or v_sale.document_status <> p_request ->> 'documentStatus'
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_sale.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_sale.action_id,
    'positionId', v_sale.position_id,
    'accountingEntryId', v_sale.accounting_entry_id,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_sale_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_sold bigint := (p_request ->> 'soldShareCount')::bigint;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_available_shares bigint;
  v_available_cost numeric;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_cost numeric;
  v_cost numeric := 0;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-sale:' || coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_sold <= 0 or v_proceeds <= 0
    or pg_catalog.round(v_proceeds, 2) <> v_proceeds
    or extract(year from (p_request ->> 'saleDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or nullif(p_request ->> 'bankTransactionId', '') is not null
    or nullif(p_request ->> 'documentId', '') is not null
    or p_request ->> 'documentStatus' = 'attached'
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.share_sales sale
    where sale.action_id = (p_request ->> 'actionId')::uuid
       or (
         sale.created_by = v_actor_id
         and sale.company_id = v_company_id
         and sale.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position
  from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid
  for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.lot_history_status <> 'complete'
  then raise exception 'investments_invalid_input'; end if;
  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id for update;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0)
  into v_available_shares, v_available_cost
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0;
  if v_available_shares = 0
    or v_available_shares::numeric <> v_position.share_count
    or v_available_cost <> v_position.cost_basis
    or v_sold > v_available_shares
  then raise exception 'investments_invalid_input'; end if;

  v_left := v_sold;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_position.id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := case
      when v_left < v_lot.remaining_share_count then v_left
      else v_lot.remaining_share_count
    end;
    v_allocated_cost := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count,
        2
      )
    end;
    v_left := v_left - v_allocated_shares;
    v_cost := v_cost + v_allocated_cost;
  end loop;
  if v_left <> 0 then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.share_sales (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, sale_date, sold_share_count, proceeds,
    fifo_cost_basis_reduction, gain_or_loss,
    remaining_share_count, remaining_cost_basis,
    bank_transaction_id, document_id, document_status, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_sale_fingerprint_v1(p_request), v_position.id, false,
    (p_request ->> 'saleDate')::date, v_sold, v_proceeds,
    v_cost, v_proceeds - v_cost,
    v_available_shares - v_sold, v_available_cost - v_cost,
    null, null, p_request ->> 'documentStatus', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id,
    'investmentName', v_position.name,
    'fifoCostBasisReduction', v_cost
  );
end;
$function$;

create or replace function ledger.investment_sale_entry_matches_v1(
  p_entry_id uuid,
  p_company_id uuid,
  p_action_id uuid
)
returns boolean language sql stable security definer set search_path = ''
as $function$
  select exists (
    select 1 from ledger.entries entry
    where entry.id = p_entry_id
      and entry.company_id = p_company_id
      and entry.entry_kind = 'SHARE_SALE'
      and entry.source_capability = 'INVESTMENTS'
      and entry.source_record_id = p_action_id::text
      and public.company_access_is_accepted_owner_v1(entry.company_id)
  );
$function$;

create or replace function backend_system.sync_legacy_share_sale_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
begin
  if new.action_type <> 'share_sale' then return new; end if;
  insert into investments.share_sales (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, accounting_entry_id, legacy_imported,
    sale_date, sold_share_count, proceeds, fifo_cost_basis_reduction,
    gain_or_loss, remaining_share_count, remaining_cost_basis,
    bank_transaction_id, document_id, document_status,
    created_by, created_at, completed_at
  ) values (
    new.id, new.company_id, new.income_year, null,
    pg_catalog.encode(extensions.digest(new.payload::text, 'sha256'), 'hex'),
    (new.payload ->> 'position_id')::uuid, new.ledger_entry_id, true,
    coalesce((new.payload ->> 'sale_date')::date, new.action_date),
    (new.payload ->> 'sold_share_count')::bigint,
    (new.payload ->> 'proceeds')::numeric,
    (new.payload ->> 'cost_basis_reduction')::numeric,
    (new.payload ->> 'gain_or_loss')::numeric,
    (new.payload ->> 'remaining_share_count')::bigint,
    (new.payload ->> 'remaining_cost_basis')::numeric,
    new.bank_transaction_id, new.document_id,
    coalesce(new.payload ->> 'document_status', 'not_required'),
    new.created_by, new.created_at,
    case when new.ledger_entry_id is null then null else new.created_at end
  ) on conflict (action_id) do nothing;
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
    sale_action_id, company_id, position_id, acquisition_lot_id,
    allocation_order, acquisition_date, allocated_share_count,
    allocated_cost_basis, created_by, created_at
  ) values (
    new.sale_action_id, new.company_id, new.position_id, new.lot_id,
    v_order, v_lot.acquisition_date, new.allocated_share_count,
    new.allocated_cost_basis, new.created_by, new.created_at
  ) on conflict (sale_action_id, acquisition_lot_id) do nothing;
  return new;
end;
$function$;

create or replace function backend_system.mirror_investment_sale_to_legacy_v1(
  p_action_id uuid,
  p_entry_id uuid,
  p_actor_id uuid
)
returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_sale investments.share_sales%rowtype;
  v_position investments.positions%rowtype;
  v_payload jsonb;
begin
  if p_actor_id is distinct from public.company_access_auth_uid_v1() then
    raise exception 'investments_forbidden';
  end if;
  perform pg_catalog.set_config('talli.investments_successor_bridge', 'on', true);
  select sale.* into v_sale from investments.share_sales sale
  where sale.action_id = p_action_id and sale.accounting_entry_id = p_entry_id;
  select position.* into v_position from investments.positions position
  where position.id = v_sale.position_id;
  if v_sale.action_id is null or v_position.id is null then
    raise exception 'investments_dependency_unavailable';
  end if;
  update public.investment_positions
  set share_count = v_position.share_count,
      cost_basis = v_position.cost_basis,
      movements = v_position.movements,
      lot_history_status = v_position.lot_history_status,
      updated_at = v_position.updated_at
  where id = v_position.id;
  update public.investment_lots legacy
  set remaining_share_count = canonical.remaining_share_count,
      remaining_cost_basis = canonical.remaining_cost_basis
  from investments.acquisition_lots canonical
  where canonical.position_id = v_position.id and legacy.id = canonical.id;
  v_payload := pg_catalog.jsonb_build_object(
    'position_id', v_sale.position_id,
    'investment_key', v_position.investment_key,
    'investment_name', v_position.name,
    'sale_date', v_sale.sale_date,
    'sold_share_count', v_sale.sold_share_count,
    'proceeds', v_sale.proceeds,
    'cost_basis_reduction', v_sale.fifo_cost_basis_reduction,
    'gain_or_loss', v_sale.gain_or_loss,
    'tax_treatment', v_position.tax_treatment,
    'remaining_share_count', v_sale.remaining_share_count,
    'remaining_cost_basis', v_sale.remaining_cost_basis,
    'lot_allocations', (
      select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.jsonb_build_object(
          'lot_id', allocation.acquisition_lot_id,
          'acquisition_date', allocation.acquisition_date,
          'share_count', allocation.allocated_share_count,
          'cost_basis', allocation.allocated_cost_basis
        ) order by allocation.allocation_order
      ), '[]'::jsonb)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id
    ),
    'bank_transaction_id', v_sale.bank_transaction_id,
    'document_id', v_sale.document_id,
    'document_status', v_sale.document_status
  );
  perform pg_catalog.set_config('talli.investment_action_write', 'on', true);
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level,
    created_by, created_at
  ) values (
    v_sale.action_id, v_sale.company_id, v_sale.income_year, 'share_sale',
    v_sale.sale_date, v_payload, p_entry_id, v_sale.bank_transaction_id,
    v_sale.document_id, 'ready', p_actor_id, v_sale.created_at
  );
  insert into public.investment_lot_allocations (
    company_id, position_id, lot_id, sale_action_id,
    allocated_share_count, allocated_cost_basis, created_by, created_at
  ) select
    allocation.company_id, allocation.position_id,
    allocation.acquisition_lot_id, allocation.sale_action_id,
    allocation.allocated_share_count, allocation.allocated_cost_basis,
    p_actor_id, allocation.created_at
  from investments.share_sale_allocations allocation
  where allocation.sale_action_id = v_sale.action_id
  order by allocation.allocation_order;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_sale.company_id, p_actor_id, 'ledger', 'share_sale_recorded',
    'Aksjesalg postert for ' || v_position.name || ' i ' || v_sale.income_year || '.'
  );
end;
$function$;

create or replace function investments.complete_share_sale_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_sale investments.share_sales%rowtype;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_cost numeric;
  v_cost numeric := 0;
  v_remaining_shares bigint;
  v_remaining_cost numeric;
  v_order integer := 0;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select sale.* into v_sale from investments.share_sales sale
  where sale.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found
    or v_sale.request_fingerprint <> investments.share_sale_fingerprint_v1(p_request)
    or not ledger.investment_sale_entry_matches_v1(
      p_entry_id, v_sale.company_id, v_sale.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_sale.accounting_entry_id is not null then
    if v_sale.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_sale.action_id,
      'positionId', v_sale.position_id,
      'accountingEntryId', v_sale.accounting_entry_id,
      'replayed', true
    );
  end if;
  select position.* into v_position from investments.positions position
  where position.id = v_sale.position_id for update;
  if not found or v_position.company_id <> v_sale.company_id
    or v_position.lot_history_status <> 'complete'
    or v_position.share_count <> v_sale.remaining_share_count + v_sale.sold_share_count
    or v_position.cost_basis < v_sale.fifo_cost_basis_reduction
  then raise exception 'investments_dependency_unavailable'; end if;

  v_left := v_sale.sold_share_count;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := case
      when v_left < v_lot.remaining_share_count then v_left
      else v_lot.remaining_share_count
    end;
    v_allocated_cost := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count,
        2
      )
    end;
    v_order := v_order + 1;
    insert into investments.share_sale_allocations (
      sale_action_id, company_id, position_id, acquisition_lot_id,
      allocation_order, acquisition_date, allocated_share_count,
      allocated_cost_basis, created_by
    ) values (
      v_sale.action_id, v_sale.company_id, v_sale.position_id, v_lot.id,
      v_order, v_lot.acquisition_date, v_allocated_shares,
      v_allocated_cost, v_actor_id
    );
    update investments.acquisition_lots
    set remaining_share_count = remaining_share_count - v_allocated_shares,
        remaining_cost_basis = remaining_cost_basis - v_allocated_cost
    where id = v_lot.id
      and remaining_share_count = v_lot.remaining_share_count
      and remaining_cost_basis = v_lot.remaining_cost_basis;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
    v_left := v_left - v_allocated_shares;
    v_cost := v_cost + v_allocated_cost;
  end loop;
  if v_left <> 0 or v_cost <> v_sale.fifo_cost_basis_reduction then
    raise exception 'investments_dependency_unavailable';
  end if;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0)
  into v_remaining_shares, v_remaining_cost
  from investments.acquisition_lots lot
  where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0;
  if v_remaining_shares <> v_sale.remaining_share_count
    or v_remaining_cost <> v_sale.remaining_cost_basis
  then raise exception 'investments_dependency_unavailable'; end if;

  update investments.positions
  set share_count = v_remaining_shares,
      cost_basis = v_remaining_cost,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'action_id', v_sale.action_id, 'movement_type', 'sale',
          'movement_date', v_sale.sale_date,
          'share_delta', -v_sale.sold_share_count,
          'cost_basis_delta', -v_sale.fifo_cost_basis_reduction,
          'amount', v_sale.proceeds, 'gain_or_loss', v_sale.gain_or_loss,
          'lot_allocations', (
            select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
              'lot_id', allocation.acquisition_lot_id,
              'acquisition_date', allocation.acquisition_date,
              'share_count', allocation.allocated_share_count,
              'cost_basis', allocation.allocated_cost_basis
            ) order by allocation.allocation_order)
            from investments.share_sale_allocations allocation
            where allocation.sale_action_id = v_sale.action_id
          )
        )
      ),
      updated_at = pg_catalog.now()
  where id = v_sale.position_id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  update investments.share_sales
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_sale.action_id;
  perform backend_system.mirror_investment_sale_to_legacy_v1(
    v_sale.action_id, p_entry_id, v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_sale.action_id,
    'positionId', v_sale.position_id,
    'accountingEntryId', p_entry_id,
    'replayed', false
  );
end;
$function$;

grant select, insert, update on investments.share_sales
  to investments_store_owner;
grant select, insert on investments.share_sale_allocations
  to investments_store_owner;
grant select on investments.share_sales, investments.share_sale_allocations
  to investments_executor;

grant select, insert, update on investments.share_sales,
  investments.share_sale_allocations to ledger_store_owner;
create policy investments_share_sales_predecessor_overlap
on investments.share_sales for all to ledger_store_owner
using (
  (
    pg_catalog.pg_trigger_depth() > 0
    or pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  )
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  (
    pg_catalog.pg_trigger_depth() > 0
    or pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  )
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_share_sale_allocations_predecessor_overlap
on investments.share_sale_allocations for all to ledger_store_owner
using (
  (
    pg_catalog.pg_trigger_depth() > 0
    or pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  )
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  (
    pg_catalog.pg_trigger_depth() > 0
    or pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  )
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

grant select, insert on public.investment_lot_allocations to ledger_store_owner;
drop policy if exists "investments successor mirrors sale allocations"
  on public.investment_lot_allocations;
create policy "investments successor mirrors sale allocations"
on public.investment_lot_allocations for insert to ledger_store_owner
with check (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

alter function investments.share_sale_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_sale_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_sale_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_sale_v1(jsonb, uuid, text)
  owner to investments_store_owner;
alter function ledger.investment_sale_entry_matches_v1(uuid, uuid, uuid)
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_share_sale_v1()
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_share_sale_allocation_v1()
  owner to ledger_store_owner;
alter function backend_system.mirror_investment_sale_to_legacy_v1(
  uuid, uuid, uuid
) owner to ledger_store_owner;

drop trigger if exists share_sales_sync_to_investments
  on public.holding_actions;
create trigger share_sales_sync_to_investments
after insert on public.holding_actions
for each row execute function backend_system.sync_legacy_share_sale_v1();
drop trigger if exists share_sale_allocations_sync_to_investments
  on public.investment_lot_allocations;
create trigger share_sale_allocations_sync_to_investments
after insert on public.investment_lot_allocations
for each row execute function backend_system.sync_legacy_share_sale_allocation_v1();

revoke all on investments.share_sales, investments.share_sale_allocations
from public, anon, authenticated, service_role;
revoke all on function
  investments.share_sale_fingerprint_v1(jsonb),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text),
  ledger.investment_sale_entry_matches_v1(uuid, uuid, uuid),
  backend_system.sync_legacy_share_sale_v1(),
  backend_system.sync_legacy_share_sale_allocation_v1(),
  backend_system.mirror_investment_sale_to_legacy_v1(uuid, uuid, uuid)
from public, anon, authenticated, service_role,
  investments_executor, investments_workflow_executor, talli_ledger_backend;

grant execute on function
  investments.share_sale_fingerprint_v1(jsonb),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text)
to investments_workflow_executor;
grant execute on function ledger.investment_sale_entry_matches_v1(uuid, uuid, uuid),
  backend_system.mirror_investment_sale_to_legacy_v1(uuid, uuid, uuid)
to investments_store_owner;

set local role ledger_store_owner;
do $investments_sale_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema ledger, backend_system from %I',
    pg_catalog.current_setting('talli.investments_sale_migration_principal')
  );
end
$investments_sale_schema_authority_revoke$;
revoke create on schema ledger, backend_system from ledger_store_owner;
reset role;

do $investments_sale_migration_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner from %I',
    current_user
  );
end
$investments_sale_migration_membership_revoke$;

commit;
