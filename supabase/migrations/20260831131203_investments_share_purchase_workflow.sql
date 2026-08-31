-- Canonical investments share-purchase workflow (issue #141).

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

drop function backend_system.prepare_investment_purchase_fifo_v1(jsonb, text);
drop function backend_system.complete_investment_purchase_fifo_v1(
  jsonb, uuid, jsonb, text
);

alter role investments_workflow_executor nologin noinherit nobypassrls;

do $block$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor to %I',
    current_user
  );
end
$block$;

grant usage on schema investments, ledger to investments_workflow_executor;

create table investments.share_purchases (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text unique,
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  position_id uuid not null references investments.positions(id) on delete restrict,
  acquisition_lot_id uuid not null unique,
  accounting_entry_id uuid unique,
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
  )
);

insert into investments.share_purchases (
  action_id, company_id, income_year, idempotency_key, request_fingerprint,
  position_id, acquisition_lot_id, accounting_entry_id,
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
to investments_executor, investments_workflow_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_share_purchases_owner_insert
on investments.share_purchases for insert
to investments_executor, investments_workflow_executor
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_share_purchases_owner_update
on investments.share_purchases for update
to investments_executor, investments_workflow_executor
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_positions_workflow_select
on investments.positions for select to investments_workflow_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_positions_workflow_insert
on investments.positions for insert to investments_workflow_executor
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_positions_workflow_update
on investments.positions for update to investments_workflow_executor
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_lots_workflow_select
on investments.acquisition_lots for select to investments_workflow_executor
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_lots_workflow_insert
on investments.acquisition_lots for insert to investments_workflow_executor
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
returns jsonb language plpgsql security invoker set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
  v_fingerprint text := investments.share_purchase_fingerprint_v1(p_request);
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select purchase.* into v_purchase
  from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid
     or purchase.idempotency_key = p_request ->> 'idempotencyKey'
  order by (purchase.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if v_purchase.request_fingerprint <> v_fingerprint
    or v_purchase.company_id <> (p_request ->> 'companyId')::uuid
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
    'positionCreated', false,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_purchase_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security invoker set search_path = ''
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
       or purchase.idempotency_key = p_request ->> 'idempotencyKey'
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
    position_id, acquisition_lot_id, investment_key, investment_name,
    investment_kind, tax_treatment, acquisition_date, share_count,
    purchase_amount, org_number, bank_transaction_id, document_id,
    document_status, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_purchase_fingerprint_v1(p_request), v_position_id, v_lot_id,
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
returns jsonb language plpgsql security invoker set search_path = ''
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
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_purchase.accounting_entry_id is not null then
    if v_purchase.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
      'lotId', v_purchase.acquisition_lot_id,
      'accountingEntryId', v_purchase.accounting_entry_id,
      'positionCreated', false, 'replayed', true
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
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id, 'accountingEntryId', p_entry_id,
    'positionCreated', (p_prepared ->> 'positionCreated')::boolean,
    'replayed', false
  );
end;
$function$;

revoke all on investments.share_purchases
from public, anon, authenticated, service_role;
revoke all on function
  investments.share_purchase_fingerprint_v1(jsonb),
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text)
from public, anon, authenticated, service_role, investments_executor,
  investments_workflow_executor;

grant select, insert, update on investments.positions,
  investments.share_purchases to investments_workflow_executor;
grant select on investments.share_purchases to investments_executor;
grant select, insert on investments.acquisition_lots
  to investments_workflow_executor;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid),
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
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor from %I',
    current_user
  );
end
$block$;
