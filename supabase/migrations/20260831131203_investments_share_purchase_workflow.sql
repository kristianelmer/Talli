-- Canonical investments share-purchase workflow (issue #141).
-- The predecessor coordinator remains available during deployment overlap and
-- is disabled only by the separately rehearsed contract release artifact.

begin;

do $block$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'investments_workflow_executor'
  ) then
    create role investments_workflow_executor nologin noinherit nobypassrls;
  end if;
end
$block$;

alter role investments_workflow_executor nologin noinherit nobypassrls;

do $block$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner to %I',
    current_user
  );
end
$block$;

grant usage on schema investments, ledger to investments_workflow_executor;

do $investments_workflow_backend_membership$
begin
  if exists (
    select 1 from pg_catalog.pg_roles where rolname = 'talli_ledger_backend'
  ) then
    grant investments_workflow_executor to talli_ledger_backend
      with inherit false, set true;
  end if;
end
$investments_workflow_backend_membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:purchase-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;

-- Close the bounded gap between the two automatic expand migrations before
-- installing overlap triggers. Existing stable IDs are updated in place.
grant select on public.investment_positions, public.investment_lots
  to investments_store_owner;
set local role investments_store_owner;
alter table investments.positions no force row level security;
alter table investments.acquisition_lots no force row level security;
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
from public.investment_positions position
on conflict (id) do update set
  investment_key = excluded.investment_key,
  name = excluded.name,
  kind = excluded.kind,
  tax_treatment = excluded.tax_treatment,
  org_number = excluded.org_number,
  share_count = excluded.share_count,
  cost_basis = excluded.cost_basis,
  movements = excluded.movements,
  lot_history_status = excluded.lot_history_status,
  updated_at = excluded.updated_at;
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
from public.investment_lots lot
on conflict (id) do update set
  remaining_share_count = excluded.remaining_share_count,
  remaining_cost_basis = excluded.remaining_cost_basis;
alter table investments.positions force row level security;
alter table investments.acquisition_lots force row level security;
reset role;
revoke select on public.investment_positions, public.investment_lots
  from investments_store_owner;

create table investments.share_purchases (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text,
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  position_id uuid not null references investments.positions(id) on delete restrict,
  acquisition_lot_id uuid not null unique,
  accounting_entry_id uuid unique,
  position_created boolean not null,
  legacy_imported boolean not null default false,
  investment_key text not null check (pg_catalog.btrim(investment_key) <> ''),
  investment_name text not null check (pg_catalog.btrim(investment_name) <> ''),
  investment_kind text not null check (investment_kind = 'norwegian_private_company'),
  tax_treatment text not null check (tax_treatment = 'fritaksmetoden'),
  acquisition_date date not null,
  share_count bigint not null check (share_count > 0),
  purchase_amount numeric(20, 2) not null check (purchase_amount > 0),
  org_number text check (org_number is null or org_number ~ '^[0-9]{9}$'),
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

insert into investments.share_purchases (
  action_id, company_id, income_year, idempotency_key, request_fingerprint,
  position_id, acquisition_lot_id, accounting_entry_id, position_created,
  legacy_imported,
  investment_key, investment_name, investment_kind, tax_treatment,
  acquisition_date, share_count, purchase_amount, org_number,
  bank_transaction_id, document_id, document_status,
  created_by, created_at, completed_at
)
select
  action.id, action.company_id, action.income_year, null,
  pg_catalog.encode(extensions.digest(action.payload::text, 'sha256'), 'hex'),
  position.id,
  lot.id,
  action.ledger_entry_id,
  not exists (
    select 1 from public.holding_actions earlier
    where earlier.action_type = 'share_purchase'
      and earlier.payload ->> 'position_id' = action.payload ->> 'position_id'
      and (earlier.created_at, earlier.id) < (action.created_at, action.id)
  ), true,
  action.payload ->> 'investment_key',
  coalesce(action.payload ->> 'investment_name', position.name),
  position.kind,
  position.tax_treatment,
  coalesce((action.payload ->> 'acquisition_date')::date, lot.acquisition_date),
  coalesce((action.payload ->> 'share_count')::bigint, lot.original_share_count),
  coalesce((action.payload ->> 'purchase_amount')::numeric, lot.original_cost_basis),
  coalesce(nullif(action.payload ->> 'org_number', ''), position.org_number),
  action.bank_transaction_id, action.document_id,
  coalesce(action.payload ->> 'document_status', 'not_required'),
  action.created_by, action.created_at,
  case when action.ledger_entry_id is null then null else action.created_at end
from public.holding_actions action
join investments.positions position
  on position.id = (action.payload ->> 'position_id')::uuid
join investments.acquisition_lots lot
  on lot.id = (action.payload ->> 'acquisition_lot_id')::uuid
where action.action_type = 'share_purchase';

create index investments_share_purchases_company_year_idx
  on investments.share_purchases(company_id, income_year, acquisition_date, action_id);

alter table investments.share_purchases owner to investments_store_owner;
alter table investments.share_purchases enable row level security;
alter table investments.share_purchases force row level security;

create policy investments_share_purchases_member_select
on investments.share_purchases for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_share_purchases_owner_insert
on investments.share_purchases for insert
to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_share_purchases_owner_update
on investments.share_purchases for update
to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_positions_workflow_select
on investments.positions for select to investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_positions_workflow_insert
on investments.positions for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_positions_workflow_update
on investments.positions for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_lots_workflow_select
on investments.acquisition_lots for select to investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_lots_workflow_insert
on investments.acquisition_lots for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function investments.share_purchase_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(p_request::text, 'sha256'), 'hex');
$function$;

create or replace function investments.get_share_purchase_replay_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
  v_fingerprint text := investments.share_purchase_fingerprint_v1(p_request);
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then
    raise exception 'investments_forbidden';
  end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-purchase:' ||
      coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then
    raise exception 'investments_idempotency_in_progress';
  end if;
  select purchase.* into v_purchase
  from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid
     or (
       purchase.created_by = v_actor_id
       and purchase.company_id = (p_request ->> 'companyId')::uuid
       and purchase.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (purchase.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (
      not v_purchase.legacy_imported
      and v_purchase.request_fingerprint <> v_fingerprint
    )
    or v_purchase.company_id <> (p_request ->> 'companyId')::uuid
    or v_purchase.income_year <> (p_request ->> 'incomeYear')::integer
    or v_purchase.investment_key <>
      pg_catalog.btrim(p_request ->> 'investmentKey')
    or v_purchase.investment_name <>
      pg_catalog.btrim(p_request ->> 'investmentName')
    or v_purchase.investment_kind <> p_request ->> 'investmentKind'
    or v_purchase.tax_treatment <> p_request ->> 'taxTreatment'
    or v_purchase.acquisition_date <> (p_request ->> 'acquisitionDate')::date
    or v_purchase.share_count <> (p_request ->> 'shareCount')::bigint
    or v_purchase.purchase_amount <> (p_request ->> 'purchaseAmount')::numeric
    or coalesce(v_purchase.org_number, '') <>
      coalesce(nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''), '')
    or v_purchase.bank_transaction_id is distinct from
      nullif(p_request ->> 'bankTransactionId', '')::uuid
    or v_purchase.document_id is distinct from
      nullif(p_request ->> 'documentId', '')::uuid
    or v_purchase.document_status <> p_request ->> 'documentStatus'
  then
    raise exception 'investments_idempotency_key_reused';
  end if;
  if v_purchase.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id,
    'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id,
    'accountingEntryId', v_purchase.accounting_entry_id,
    'positionCreated', v_purchase.position_created,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_purchase_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_position_id uuid;
  v_position_created boolean := false;
  v_lot_id uuid := extensions.gen_random_uuid();
  v_amount numeric := (p_request ->> 'purchaseAmount')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-purchase:' || coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then
    raise exception 'investments_idempotency_in_progress';
  end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_request ->> 'investmentKey', '')) = ''
    or pg_catalog.btrim(coalesce(p_request ->> 'investmentName', '')) = ''
    or p_request ->> 'investmentKind' <> 'norwegian_private_company'
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or (p_request ->> 'shareCount')::bigint <= 0
    or v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or extract(year from (p_request ->> 'acquisitionDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or (
      nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), '') is not null
      and pg_catalog.btrim(p_request ->> 'orgNumber') !~ '^[0-9]{9}$'
    )
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or nullif(p_request ->> 'bankTransactionId', '') is not null
    or nullif(p_request ->> 'documentId', '') is not null
    or p_request ->> 'documentStatus' = 'attached'
  then raise exception 'investments_invalid_input'; end if;

  if exists (
    select 1 from investments.share_purchases purchase
    where purchase.action_id = (p_request ->> 'actionId')::uuid
       or (
         purchase.created_by = v_actor_id
         and purchase.company_id = v_company_id
         and purchase.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  insert into investments.positions (
    company_id, investment_key, name, kind, tax_treatment, org_number,
    share_count, cost_basis, movements, lot_history_status, created_by
  ) values (
    v_company_id, pg_catalog.btrim(p_request ->> 'investmentKey'),
    pg_catalog.btrim(p_request ->> 'investmentName'),
    p_request ->> 'investmentKind', p_request ->> 'taxTreatment',
    nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''),
    0, 0, '[]'::jsonb, 'complete', v_actor_id
  ) on conflict (company_id, investment_key) do nothing returning id into v_position_id;
  if v_position_id is null then
    select position.* into v_position from investments.positions position
    where position.company_id = v_company_id
      and position.investment_key = pg_catalog.btrim(p_request ->> 'investmentKey')
    for update;
    if not found or v_position.kind <> p_request ->> 'investmentKind'
      or v_position.tax_treatment <> p_request ->> 'taxTreatment'
      or coalesce(v_position.org_number, '') <>
        coalesce(nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''), '')
    then raise exception 'investments_invalid_input'; end if;
    v_position_id := v_position.id;
  else
    v_position_created := true;
  end if;

  insert into investments.share_purchases (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, acquisition_lot_id, position_created, legacy_imported,
    investment_key, investment_name,
    investment_kind, tax_treatment, acquisition_date, share_count,
    purchase_amount, org_number, bank_transaction_id, document_id,
    document_status, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_purchase_fingerprint_v1(p_request), v_position_id, v_lot_id,
    v_position_created, false,
    pg_catalog.btrim(p_request ->> 'investmentKey'),
    pg_catalog.btrim(p_request ->> 'investmentName'),
    p_request ->> 'investmentKind', p_request ->> 'taxTreatment',
    (p_request ->> 'acquisitionDate')::date,
    (p_request ->> 'shareCount')::bigint, v_amount,
    nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''),
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position_id, 'lotId', v_lot_id,
    'positionCreated', v_position_created,
    'investmentName', pg_catalog.btrim(p_request ->> 'investmentName'),
    'purchaseAmount', v_amount
  );
end;
$function$;

create or replace function investments.complete_share_purchase_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select purchase.* into v_purchase
  from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid
  for update;
  if not found
    or v_purchase.request_fingerprint <>
      investments.share_purchase_fingerprint_v1(p_request)
    or v_purchase.position_id <> (p_prepared ->> 'positionId')::uuid
    or v_purchase.acquisition_lot_id <> (p_prepared ->> 'lotId')::uuid
    or v_purchase.position_created <>
      (p_prepared ->> 'positionCreated')::boolean
    or not ledger.investment_entry_matches_v1(
      p_entry_id, v_purchase.company_id, v_purchase.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_purchase.accounting_entry_id is not null then
    if v_purchase.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
      'lotId', v_purchase.acquisition_lot_id,
      'accountingEntryId', v_purchase.accounting_entry_id,
      'positionCreated', v_purchase.position_created, 'replayed', true
    );
  end if;

  insert into investments.acquisition_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by
  ) values (
    v_purchase.acquisition_lot_id, v_purchase.company_id, v_purchase.position_id,
    v_purchase.action_id, v_purchase.acquisition_date,
    v_purchase.share_count, v_purchase.share_count,
    v_purchase.purchase_amount, v_purchase.purchase_amount, v_actor_id
  );
  update investments.positions
  set share_count = share_count + v_purchase.share_count,
      cost_basis = cost_basis + v_purchase.purchase_amount,
      movements = movements || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'action_id', v_purchase.action_id, 'movement_type', 'purchase',
        'movement_date', v_purchase.acquisition_date,
        'share_delta', v_purchase.share_count,
        'cost_basis_delta', v_purchase.purchase_amount,
        'amount', v_purchase.purchase_amount,
        'lot_id', v_purchase.acquisition_lot_id
      )),
      updated_at = pg_catalog.now()
  where id = v_purchase.position_id;
  update investments.share_purchases
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_purchase.action_id;
  perform backend_system.mirror_investment_purchase_to_successor_v1(
    v_purchase.action_id, p_entry_id, v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id, 'accountingEntryId', p_entry_id,
    'positionCreated', v_purchase.position_created,
    'replayed', false
  );
end;
$function$;

-- The sale and received-dividend slices remain serialized successors. During
-- their bounded overlap, keep their frozen public storage projection in the
-- same transaction and mirror predecessor sale mutations back to the canonical
-- owner. These bridges own no purchase or FIFO policy and are removed by the
-- successor slices.
grant usage on schema investments to ledger_store_owner;
grant usage on schema ledger, backend_system to investments_store_owner;
grant select, insert, update on investments.positions,
  investments.acquisition_lots, investments.share_purchases
to ledger_store_owner;

create policy investments_positions_successor_overlap
on investments.positions for all to ledger_store_owner
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
create policy investments_lots_successor_overlap
on investments.acquisition_lots for all to ledger_store_owner
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
create policy investments_purchases_successor_overlap
on investments.share_purchases for all to ledger_store_owner
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

grant select, insert, update on public.investment_positions,
  public.investment_lots to ledger_store_owner;
grant select, insert on public.holding_actions, public.audit_events
  to ledger_store_owner;

drop policy if exists "investments successor mirrors positions"
  on public.investment_positions;
create policy "investments successor mirrors positions"
on public.investment_positions for all to ledger_store_owner
using (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "investments successor mirrors lots"
  on public.investment_lots;
create policy "investments successor mirrors lots"
on public.investment_lots for all to ledger_store_owner
using (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "investments successor mirrors actions"
  on public.holding_actions;
create policy "investments successor mirrors actions"
on public.holding_actions for insert to ledger_store_owner
with check (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "investments successor appends audit"
  on public.audit_events;
create policy "investments successor appends audit"
on public.audit_events for insert to ledger_store_owner
with check (
  pg_catalog.current_setting('talli.investments_successor_bridge', true) = 'on'
  and actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

select pg_catalog.set_config(
  'talli.investments_migration_principal', current_user, true
);
set local role ledger_store_owner;
do $investments_bridge_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema ledger, backend_system to %I',
    pg_catalog.current_setting('talli.investments_migration_principal')
  );
end
$investments_bridge_schema_authority$;
reset role;

create or replace function ledger.investment_entry_matches_v1(
  p_entry_id uuid,
  p_company_id uuid,
  p_action_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from ledger.entries entry
    where entry.id = p_entry_id
      and entry.company_id = p_company_id
      and entry.entry_kind = 'SHARE_PURCHASE'
      and entry.source_capability = 'INVESTMENTS'
      and entry.source_record_id = p_action_id::text
      and public.company_access_is_accepted_owner_v1(entry.company_id)
  );
$function$;

create or replace function backend_system.sync_legacy_investment_position_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  insert into investments.positions (
    id, company_id, investment_key, name, kind, tax_treatment, org_number,
    share_count, cost_basis, movements, lot_history_status,
    created_by, created_at, updated_at
  ) values (
    new.id, new.company_id, new.investment_key, new.name, new.kind,
    new.tax_treatment, new.org_number, new.share_count::bigint,
    new.cost_basis, new.movements, new.lot_history_status,
    new.created_by, new.created_at, new.updated_at
  ) on conflict (id) do update set
    investment_key = excluded.investment_key,
    name = excluded.name,
    kind = excluded.kind,
    tax_treatment = excluded.tax_treatment,
    org_number = excluded.org_number,
    share_count = excluded.share_count,
    cost_basis = excluded.cost_basis,
    movements = excluded.movements,
    lot_history_status = excluded.lot_history_status,
    updated_at = excluded.updated_at;
  return new;
end;
$function$;

create or replace function backend_system.sync_legacy_investment_lot_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  insert into investments.acquisition_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by, created_at
  ) values (
    new.id, new.company_id, new.position_id, new.acquisition_action_id,
    new.acquisition_date, new.original_share_count, new.remaining_share_count,
    new.original_cost_basis, new.remaining_cost_basis,
    new.created_by, new.created_at
  ) on conflict (id) do update set
    remaining_share_count = excluded.remaining_share_count,
    remaining_cost_basis = excluded.remaining_cost_basis;
  return new;
end;
$function$;

create or replace function backend_system.sync_legacy_share_purchase_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
begin
  if new.action_type <> 'share_purchase' then return new; end if;
  select * into v_position from investments.positions
  where id = (new.payload ->> 'position_id')::uuid;
  select * into v_lot from investments.acquisition_lots
  where id = (new.payload ->> 'acquisition_lot_id')::uuid;
  if not found then
    -- The predecessor inserts its holding action before its lot. The lot trigger
    -- completes canonical lot synchronization later in the same transaction.
    null;
  end if;
  insert into investments.share_purchases (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, acquisition_lot_id, accounting_entry_id,
    position_created, legacy_imported,
    investment_key, investment_name, investment_kind, tax_treatment,
    acquisition_date, share_count, purchase_amount, org_number,
    bank_transaction_id, document_id, document_status,
    created_by, created_at, completed_at
  ) values (
    new.id, new.company_id, new.income_year, null,
    pg_catalog.encode(extensions.digest(new.payload::text, 'sha256'), 'hex'),
    (new.payload ->> 'position_id')::uuid,
    (new.payload ->> 'acquisition_lot_id')::uuid,
    new.ledger_entry_id,
    not exists (
      select 1 from investments.share_purchases earlier
      where earlier.position_id = (new.payload ->> 'position_id')::uuid
    ),
    true,
    new.payload ->> 'investment_key',
    coalesce(new.payload ->> 'investment_name', v_position.name),
    coalesce(new.payload ->> 'investment_kind', v_position.kind),
    coalesce(new.payload ->> 'tax_treatment', v_position.tax_treatment),
    coalesce((new.payload ->> 'acquisition_date')::date, new.action_date),
    (new.payload ->> 'share_count')::bigint,
    (new.payload ->> 'purchase_amount')::numeric,
    coalesce(nullif(new.payload ->> 'org_number', ''), v_position.org_number),
    new.bank_transaction_id, new.document_id,
    coalesce(new.payload ->> 'document_status', 'not_required'),
    new.created_by, new.created_at,
    case when new.ledger_entry_id is null then null else new.created_at end
  ) on conflict (action_id) do nothing;
  return new;
end;
$function$;

create or replace function backend_system.mirror_investment_purchase_to_successor_v1(
  p_action_id uuid,
  p_entry_id uuid,
  p_actor_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_purchase investments.share_purchases%rowtype;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_payload jsonb;
begin
  if p_actor_id is distinct from public.company_access_auth_uid_v1() then
    raise exception 'investments_forbidden';
  end if;
  perform pg_catalog.set_config('talli.investments_successor_bridge', 'on', true);
  select * into v_purchase from investments.share_purchases
  where action_id = p_action_id and accounting_entry_id = p_entry_id;
  select * into v_position from investments.positions
  where id = v_purchase.position_id;
  select * into v_lot from investments.acquisition_lots
  where id = v_purchase.acquisition_lot_id;
  if v_purchase.action_id is null or v_position.id is null or v_lot.id is null then
    raise exception 'investments_dependency_unavailable';
  end if;
  insert into public.investment_positions (
    id, company_id, investment_key, name, kind, tax_treatment, org_number,
    share_count, cost_basis, movements, lot_history_status,
    created_by, created_at, updated_at
  ) values (
    v_position.id, v_position.company_id, v_position.investment_key,
    v_position.name, v_position.kind, v_position.tax_treatment,
    v_position.org_number, v_position.share_count, v_position.cost_basis,
    v_position.movements, v_position.lot_history_status,
    v_position.created_by, v_position.created_at, v_position.updated_at
  ) on conflict (id) do update set
    share_count = excluded.share_count,
    cost_basis = excluded.cost_basis,
    movements = excluded.movements,
    lot_history_status = excluded.lot_history_status,
    updated_at = excluded.updated_at;
  v_payload := pg_catalog.jsonb_build_object(
    'investment_key', v_purchase.investment_key,
    'investment_name', v_purchase.investment_name,
    'investment_kind', v_purchase.investment_kind,
    'tax_treatment', v_purchase.tax_treatment,
    'acquisition_date', v_purchase.acquisition_date,
    'share_count', v_purchase.share_count,
    'purchase_amount', v_purchase.purchase_amount,
    'org_number', v_purchase.org_number,
    'bank_transaction_id', v_purchase.bank_transaction_id,
    'document_id', v_purchase.document_id,
    'document_status', v_purchase.document_status,
    'acquisition_lot_id', v_purchase.acquisition_lot_id,
    'position_id', v_purchase.position_id
  );
  perform pg_catalog.set_config('talli.investment_action_write', 'on', true);
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by,
    created_at
  ) values (
    v_purchase.action_id, v_purchase.company_id, v_purchase.income_year,
    'share_purchase', v_purchase.acquisition_date, v_payload, p_entry_id,
    v_purchase.bank_transaction_id, v_purchase.document_id, 'ready',
    p_actor_id, v_purchase.created_at
  );
  insert into public.investment_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by, created_at
  ) values (
    v_lot.id, v_lot.company_id, v_lot.position_id,
    v_lot.acquisition_action_id, v_lot.acquisition_date,
    v_lot.original_share_count, v_lot.remaining_share_count,
    v_lot.original_cost_basis, v_lot.remaining_cost_basis,
    v_lot.created_by, v_lot.created_at
  );
  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_purchase.company_id, p_actor_id, 'ledger', 'share_purchase_recorded',
    'Aksjekjøp postert for ' || v_purchase.investment_name || ' i ' ||
      v_purchase.income_year || '.'
  );
end;
$function$;

alter function ledger.investment_entry_matches_v1(uuid, uuid, uuid)
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_investment_position_v1()
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_investment_lot_v1()
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_share_purchase_v1()
  owner to ledger_store_owner;
alter function backend_system.mirror_investment_purchase_to_successor_v1(
  uuid, uuid, uuid
) owner to ledger_store_owner;

set local role ledger_store_owner;
do $investments_bridge_schema_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema ledger, backend_system from %I',
    pg_catalog.current_setting('talli.investments_migration_principal')
  );
end
$investments_bridge_schema_revoke$;
reset role;

drop trigger if exists investment_positions_sync_to_investments
  on public.investment_positions;
create trigger investment_positions_sync_to_investments
after insert or update on public.investment_positions
for each row execute function backend_system.sync_legacy_investment_position_v1();
drop trigger if exists investment_lots_sync_to_investments
  on public.investment_lots;
create trigger investment_lots_sync_to_investments
after insert or update on public.investment_lots
for each row execute function backend_system.sync_legacy_investment_lot_v1();
drop trigger if exists share_purchases_sync_to_investments
  on public.holding_actions;
create trigger share_purchases_sync_to_investments
after insert on public.holding_actions
for each row execute function backend_system.sync_legacy_share_purchase_v1();

revoke all on function ledger.investment_entry_matches_v1(uuid, uuid, uuid),
  backend_system.sync_legacy_investment_position_v1(),
  backend_system.sync_legacy_investment_lot_v1(),
  backend_system.sync_legacy_share_purchase_v1(),
  backend_system.mirror_investment_purchase_to_successor_v1(uuid, uuid, uuid)
from public, anon, authenticated, service_role, investments_executor,
  investments_workflow_executor, talli_ledger_backend;
grant execute on function ledger.investment_entry_matches_v1(uuid, uuid, uuid)
  to investments_store_owner;
grant execute on function
  backend_system.mirror_investment_purchase_to_successor_v1(uuid, uuid, uuid)
to investments_store_owner;

alter function investments.share_purchase_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_purchase_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_purchase_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text)
  owner to investments_store_owner;

revoke all on investments.share_purchases
from public, anon, authenticated, service_role;
revoke all on function
  investments.share_purchase_fingerprint_v1(jsonb),
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text)
from public, anon, authenticated, service_role, investments_executor,
  investments_workflow_executor;

grant select, insert, update on investments.share_purchases
  to investments_store_owner;
grant select on investments.share_purchases to investments_executor;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid)
to investments_store_owner;
grant execute on function
  investments.share_purchase_fingerprint_v1(jsonb),
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text),
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  ),
  ledger.post_entry_with_id_v1(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text, uuid
  )
to investments_workflow_executor;

do $block$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner from %I',
    current_user
  );
end
$block$;

commit;
