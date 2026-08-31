-- Canonical investments received-dividend workflow (issue #143).
-- The predecessor coordinator remains callable during the expand window.

begin;

do $investments_dividend_migration_membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner to %I',
    current_user
  );
end
$investments_dividend_migration_membership$;

select pg_catalog.set_config(
  'talli.investments_dividend_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema ledger, backend_system to ledger_store_owner;
do $investments_dividend_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema ledger, backend_system to %I',
    pg_catalog.current_setting('talli.investments_dividend_migration_principal')
  );
end
$investments_dividend_schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:dividend-cutover:v1', 0)
);
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;

create table investments.received_dividends (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text,
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  position_id uuid not null references investments.positions(id) on delete restrict,
  accounting_entry_id uuid unique,
  legacy_imported boolean not null default false,
  paying_company_name text not null check (
    paying_company_name = pg_catalog.btrim(paying_company_name)
    and paying_company_name <> ''
    and pg_catalog.length(paying_company_name) <= 255
  ),
  declared_date date not null,
  paid_date date not null,
  gross_amount numeric(20, 2) not null check (gross_amount > 0),
  tax_treatment text not null check (tax_treatment = 'fritaksmetoden'),
  taxable_add_back numeric(20, 2) not null check (taxable_add_back >= 0),
  bank_transaction_id uuid,
  document_id uuid,
  document_status text not null check (
    document_status in ('attached', 'missing_accepted_warning', 'not_required')
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  completed_at timestamptz,
  check (declared_date <= paid_date),
  check (
    (accounting_entry_id is null and completed_at is null)
    or (accounting_entry_id is not null and completed_at is not null)
  ),
  unique (created_by, company_id, idempotency_key)
);

insert into investments.received_dividends (
  action_id, company_id, income_year, idempotency_key, request_fingerprint,
  position_id, accounting_entry_id, legacy_imported, paying_company_name,
  declared_date, paid_date, gross_amount, tax_treatment, taxable_add_back,
  bank_transaction_id, document_id, document_status,
  created_by, created_at, completed_at
)
select
  action.id, action.company_id, action.income_year, null,
  pg_catalog.encode(extensions.digest(action.payload::text, 'sha256'), 'hex'),
  position.id, action.ledger_entry_id, true,
  pg_catalog.btrim(action.payload ->> 'paying_company_name'),
  (action.payload ->> 'declared_date')::date,
  coalesce((action.payload ->> 'paid_date')::date, action.action_date),
  (action.payload ->> 'gross_amount')::numeric,
  coalesce(action.payload ->> 'tax_treatment', 'fritaksmetoden'),
  coalesce(
    (action.payload ->> 'taxable_add_back')::numeric,
    pg_catalog.round((action.payload ->> 'gross_amount')::numeric * 0.03, 2)
  ),
  action.bank_transaction_id, action.document_id,
  coalesce(action.payload ->> 'document_status', 'not_required'),
  action.created_by, action.created_at,
  case when action.ledger_entry_id is null then null else action.created_at end
from public.holding_actions action
join investments.positions position
  on position.company_id = action.company_id
  and (
    position.id::text = action.payload ->> 'linked_investment_id'
    or position.investment_key = action.payload ->> 'linked_investment_id'
  )
where action.action_type = 'dividend_received';

create index investments_received_dividends_company_year_idx
  on investments.received_dividends(company_id, income_year, paid_date, action_id);

alter table investments.received_dividends owner to investments_store_owner;
alter table investments.received_dividends enable row level security;
alter table investments.received_dividends force row level security;

create policy investments_received_dividends_member_select
on investments.received_dividends for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_received_dividends_owner_insert
on investments.received_dividends for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy investments_received_dividends_owner_update
on investments.received_dividends for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function investments.received_dividend_fingerprint_v1(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(p_request::text, 'sha256'), 'hex');
$function$;

create or replace function investments.get_received_dividend_replay_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_dividend investments.received_dividends%rowtype;
  v_fingerprint text := investments.received_dividend_fingerprint_v1(p_request);
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':received-dividend:' ||
      coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select dividend.* into v_dividend
  from investments.received_dividends dividend
  where dividend.action_id = (p_request ->> 'actionId')::uuid
     or (
       dividend.created_by = v_actor_id
       and dividend.company_id = (p_request ->> 'companyId')::uuid
       and dividend.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (dividend.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (
      not v_dividend.legacy_imported
      and v_dividend.request_fingerprint <> v_fingerprint
    )
    or v_dividend.company_id <> (p_request ->> 'companyId')::uuid
    or v_dividend.income_year <> (p_request ->> 'incomeYear')::integer
    or v_dividend.position_id <> (p_request ->> 'positionId')::uuid
    or v_dividend.paying_company_name <> pg_catalog.btrim(
      p_request ->> 'payingCompanyName'
    )
    or v_dividend.declared_date <> (p_request ->> 'declaredDate')::date
    or v_dividend.paid_date <> (p_request ->> 'paidDate')::date
    or v_dividend.gross_amount <> (p_request ->> 'grossAmount')::numeric
    or v_dividend.tax_treatment <> p_request ->> 'taxTreatment'
    or v_dividend.taxable_add_back <> (p_request ->> 'taxableAddBack')::numeric
    or v_dividend.bank_transaction_id is distinct from
      nullif(p_request ->> 'bankTransactionId', '')::uuid
    or v_dividend.document_id is distinct from
      nullif(p_request ->> 'documentId', '')::uuid
    or v_dividend.document_status <> p_request ->> 'documentStatus'
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_dividend.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_dividend.action_id,
    'positionId', v_dividend.position_id,
    'accountingEntryId', v_dividend.accounting_entry_id,
    'taxableAddBack', v_dividend.taxable_add_back,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_received_dividend_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'payingCompanyName');
  v_gross numeric := (p_request ->> 'grossAmount')::numeric;
  v_add_back numeric := (p_request ->> 'taxableAddBack')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':received-dividend:' || coalesce(p_request ->> 'idempotencyKey', ''),
    0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_gross <= 0 or pg_catalog.round(v_gross, 2) <> v_gross
    or v_add_back < 0 or pg_catalog.round(v_add_back, 2) <> v_add_back
    or (p_request ->> 'declaredDate')::date > (p_request ->> 'paidDate')::date
    or extract(year from (p_request ->> 'declaredDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or extract(year from (p_request ->> 'paidDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or nullif(p_request ->> 'bankTransactionId', '') is not null
    or nullif(p_request ->> 'documentId', '') is not null
    or p_request ->> 'documentStatus' = 'attached'
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.received_dividends dividend
    where dividend.action_id = (p_request ->> 'actionId')::uuid
       or (
         dividend.created_by = v_actor_id
         and dividend.company_id = v_company_id
         and dividend.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.tax_treatment <> 'fritaksmetoden'
  then raise exception 'investments_invalid_input'; end if;
  insert into investments.received_dividends (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, paying_company_name, declared_date,
    paid_date, gross_amount, tax_treatment, taxable_add_back,
    bank_transaction_id, document_id, document_status, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.received_dividend_fingerprint_v1(p_request), v_position.id,
    false, v_name, (p_request ->> 'declaredDate')::date,
    (p_request ->> 'paidDate')::date, v_gross, 'fritaksmetoden', v_add_back,
    null, null, p_request ->> 'documentStatus', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id,
    'investmentName', v_position.name,
    'payingCompanyName', v_name,
    'taxableAddBack', v_add_back
  );
end;
$function$;

create or replace function ledger.investment_dividend_entry_matches_v1(
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
      and entry.entry_kind = 'DIVIDEND_RECEIVED'
      and entry.source_capability = 'INVESTMENTS'
      and entry.source_record_id = p_action_id::text
      and public.company_access_is_accepted_owner_v1(entry.company_id)
  );
$function$;

create or replace function backend_system.sync_legacy_received_dividend_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
declare
  v_position_id uuid;
begin
  if new.action_type <> 'dividend_received' then return new; end if;
  select position.id into v_position_id from investments.positions position
  where position.company_id = new.company_id
    and (
      position.id::text = new.payload ->> 'linked_investment_id'
      or position.investment_key = new.payload ->> 'linked_investment_id'
    )
  limit 1;
  if v_position_id is null then raise exception 'investments_dependency_unavailable'; end if;
  insert into investments.received_dividends (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, accounting_entry_id, legacy_imported, paying_company_name,
    declared_date, paid_date, gross_amount, tax_treatment, taxable_add_back,
    bank_transaction_id, document_id, document_status,
    created_by, created_at, completed_at
  ) values (
    new.id, new.company_id, new.income_year, null,
    pg_catalog.encode(extensions.digest(new.payload::text, 'sha256'), 'hex'),
    v_position_id, new.ledger_entry_id, true,
    pg_catalog.btrim(new.payload ->> 'paying_company_name'),
    (new.payload ->> 'declared_date')::date,
    coalesce((new.payload ->> 'paid_date')::date, new.action_date),
    (new.payload ->> 'gross_amount')::numeric,
    coalesce(new.payload ->> 'tax_treatment', 'fritaksmetoden'),
    coalesce(
      (new.payload ->> 'taxable_add_back')::numeric,
      pg_catalog.round((new.payload ->> 'gross_amount')::numeric * 0.03, 2)
    ),
    new.bank_transaction_id, new.document_id,
    coalesce(new.payload ->> 'document_status', 'not_required'),
    new.created_by, new.created_at,
    case when new.ledger_entry_id is null then null else new.created_at end
  ) on conflict (action_id) do nothing;
  return new;
end;
$function$;

create or replace function backend_system.mirror_received_dividend_to_legacy_v1(
  p_action_id uuid,
  p_entry_id uuid,
  p_actor_id uuid
)
returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_dividend investments.received_dividends%rowtype;
  v_position investments.positions%rowtype;
begin
  if p_actor_id is distinct from public.company_access_auth_uid_v1() then
    raise exception 'investments_forbidden';
  end if;
  perform pg_catalog.set_config('talli.investments_successor_bridge', 'on', true);
  select dividend.* into v_dividend
  from investments.received_dividends dividend
  where dividend.action_id = p_action_id
    and dividend.accounting_entry_id = p_entry_id;
  select position.* into v_position from investments.positions position
  where position.id = v_dividend.position_id;
  if v_dividend.action_id is null or v_position.id is null then
    raise exception 'investments_dependency_unavailable';
  end if;
  perform pg_catalog.set_config('talli.investment_action_write', 'on', true);
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level,
    created_by, created_at
  ) values (
    v_dividend.action_id, v_dividend.company_id, v_dividend.income_year,
    'dividend_received', v_dividend.paid_date,
    pg_catalog.jsonb_build_object(
      'paying_company_name', v_dividend.paying_company_name,
      'declared_date', v_dividend.declared_date,
      'paid_date', v_dividend.paid_date,
      'gross_amount', v_dividend.gross_amount,
      'linked_investment_id', v_position.id,
      'tax_treatment', v_dividend.tax_treatment,
      'taxable_add_back', v_dividend.taxable_add_back,
      'bank_transaction_id', v_dividend.bank_transaction_id,
      'document_id', v_dividend.document_id,
      'document_status', v_dividend.document_status
    ),
    p_entry_id, v_dividend.bank_transaction_id, v_dividend.document_id,
    'ready', p_actor_id, v_dividend.created_at
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_dividend.company_id, p_actor_id, 'ledger',
    'dividend_received_recorded',
    'Mottatt utbytte postert fra ' || v_dividend.paying_company_name ||
      ' for ' || v_dividend.income_year || '.'
  );
end;
$function$;

create or replace function investments.complete_received_dividend_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_dividend investments.received_dividends%rowtype;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select dividend.* into v_dividend
  from investments.received_dividends dividend
  where dividend.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found
    or v_dividend.request_fingerprint <>
      investments.received_dividend_fingerprint_v1(p_request)
    or not ledger.investment_dividend_entry_matches_v1(
      p_entry_id, v_dividend.company_id, v_dividend.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_dividend.accounting_entry_id is not null then
    if v_dividend.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_dividend.action_id,
      'positionId', v_dividend.position_id,
      'accountingEntryId', v_dividend.accounting_entry_id,
      'taxableAddBack', v_dividend.taxable_add_back,
      'replayed', true
    );
  end if;
  update investments.received_dividends
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_dividend.action_id and accounting_entry_id is null;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  perform backend_system.mirror_received_dividend_to_legacy_v1(
    v_dividend.action_id, p_entry_id, v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_dividend.action_id,
    'positionId', v_dividend.position_id,
    'accountingEntryId', p_entry_id,
    'taxableAddBack', v_dividend.taxable_add_back,
    'replayed', false
  );
end;
$function$;

grant select, insert, update on investments.received_dividends
  to investments_store_owner;
grant select on investments.received_dividends to investments_executor;
grant select, insert, update on investments.received_dividends
  to ledger_store_owner;

create policy investments_received_dividends_predecessor_overlap
on investments.received_dividends for all to ledger_store_owner
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

alter function investments.received_dividend_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_received_dividend_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_dividend_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_received_dividend_v1(jsonb, uuid, text)
  owner to investments_store_owner;
alter function ledger.investment_dividend_entry_matches_v1(uuid, uuid, uuid)
  owner to ledger_store_owner;
alter function backend_system.sync_legacy_received_dividend_v1()
  owner to ledger_store_owner;
alter function backend_system.mirror_received_dividend_to_legacy_v1(
  uuid, uuid, uuid
) owner to ledger_store_owner;

drop trigger if exists received_dividends_sync_to_investments
  on public.holding_actions;
create trigger received_dividends_sync_to_investments
after insert on public.holding_actions
for each row execute function backend_system.sync_legacy_received_dividend_v1();

revoke all on investments.received_dividends
from public, anon, authenticated, service_role;
revoke all on function
  investments.received_dividend_fingerprint_v1(jsonb),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text),
  ledger.investment_dividend_entry_matches_v1(uuid, uuid, uuid),
  backend_system.sync_legacy_received_dividend_v1(),
  backend_system.mirror_received_dividend_to_legacy_v1(uuid, uuid, uuid)
from public, anon, authenticated, service_role,
  investments_executor, investments_workflow_executor, talli_ledger_backend;

grant execute on function
  investments.received_dividend_fingerprint_v1(jsonb),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text)
to investments_workflow_executor;
grant execute on function
  ledger.investment_dividend_entry_matches_v1(uuid, uuid, uuid),
  backend_system.mirror_received_dividend_to_legacy_v1(uuid, uuid, uuid)
to investments_store_owner;

set local role ledger_store_owner;
do $investments_dividend_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema ledger, backend_system from %I',
    pg_catalog.current_setting('talli.investments_dividend_migration_principal')
  );
end
$investments_dividend_schema_authority_revoke$;
revoke create on schema ledger, backend_system from ledger_store_owner;
reset role;

do $investments_dividend_migration_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner from %I',
    current_user
  );
end
$investments_dividend_migration_membership_revoke$;

commit;
