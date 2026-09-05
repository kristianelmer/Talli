-- Durable annual refund requests and single-assignment execution binding.
-- Existing owner/support-case authorization is preserved; no worker is activated.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.annual_refund_requests_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.annual_refund_requests_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.annual_refund_requests_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
-- Borrow only missing FK-reference privileges for the migration principal.
do $references$
declare v_principal text := current_user; v_table text; v_missing text[] := array[]::text[];
begin
  foreach v_table in array array['annual_purchases','annual_refund_cases','annual_operations'] loop
    if not pg_catalog.has_column_privilege(v_principal, 'billing.' || v_table, 'id', 'REFERENCES') then
      v_missing := pg_catalog.array_append(v_missing, v_table);
      set local role billing_store_owner;
      execute pg_catalog.format('grant references (id) on billing.%I to %I', v_table, v_principal);
      reset role;
    end if;
  end loop;
  perform pg_catalog.set_config('talli.annual_refund_requests_borrowed_references', pg_catalog.array_to_string(v_missing, ','), true);
end;
$references$;

do $restore$
begin
  if pg_catalog.to_regclass('billing.annual_refund_requests') is null
    and pg_catalog.to_regclass('billing_annual_retired.annual_refund_requests') is not null then
    alter table billing_annual_retired.annual_refund_requests set schema billing;
  end if;
end;
$restore$;

create table if not exists billing.annual_refund_requests (
  id uuid primary key,
  purchase_id uuid not null references billing.annual_purchases(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  refund_case_id uuid not null references billing.annual_refund_cases(id) on delete restrict,
  operation_id uuid references billing.annual_operations(id) on delete restrict,
  requested_by uuid not null references auth.users(id) on delete restrict,
  requested_at timestamptz not null default pg_catalog.statement_timestamp(),
  correlation_id text not null check (length(correlation_id) between 1 and 200),
  idempotency_key text not null unique check (length(idempotency_key) between 8 and 200),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$')
);
create index if not exists annual_refund_request_purchase on billing.annual_refund_requests(purchase_id);
create index if not exists annual_refund_request_company on billing.annual_refund_requests(company_id);
create index if not exists annual_refund_request_case on billing.annual_refund_requests(refund_case_id);
create index if not exists annual_refund_request_operation on billing.annual_refund_requests(operation_id);
create index if not exists annual_refund_request_actor on billing.annual_refund_requests(requested_by);
alter table billing.annual_refund_requests owner to billing_store_owner;
set local role billing_store_owner;
alter table billing.annual_refund_requests enable row level security;
alter table billing.annual_refund_requests force row level security;
revoke all on billing.annual_refund_requests from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
grant select, insert, update (operation_id), trigger on billing.annual_refund_requests to billing_store_owner;

create or replace function billing.guard_annual_refund_request_v1()
returns trigger language plpgsql set search_path = '' as $function$
declare v_purchase billing.annual_purchases%rowtype;
begin
  if tg_op = 'DELETE' then raise exception 'annual_refund_request_is_immutable'; end if;
  if tg_op = 'UPDATE' and (
    (pg_catalog.to_jsonb(new) - 'operation_id') is distinct from (pg_catalog.to_jsonb(old) - 'operation_id')
    or old.operation_id is not null
  ) then raise exception 'annual_refund_request_is_immutable'; end if;
  -- A deferred request may acquire one operation later; request identity never changes.
  select * into v_purchase from billing.annual_purchases where id=new.purchase_id for update;
  if not found or v_purchase.company_id<>new.company_id or v_purchase.income_year<>new.income_year
    or not exists (select 1 from billing.annual_refund_cases c where c.id=new.refund_case_id
      and c.purchase_id=new.purchase_id and c.company_id=new.company_id and c.income_year=new.income_year)
  then raise exception 'annual_refund_request_not_available'; end if;
  if new.operation_id is not null and not exists (
    select 1 from billing.annual_operations o where o.id=new.operation_id and o.operation='refund'
      and o.refund_case_id=new.refund_case_id and o.purchase_id=new.purchase_id
      and o.company_id=new.company_id and o.income_year=new.income_year
  ) then raise exception 'annual_refund_request_not_available'; end if;
  return new;
end;
$function$;

create or replace function billing.apply_annual_refund_request_v1()
returns trigger language plpgsql set search_path = '' as $function$
begin
  -- AFTER INSERT avoids a side effect when ON CONFLICT skips the durable request.
  update billing.annual_purchases set renewal_canceled_at=pg_catalog.statement_timestamp(),
    updated_at=pg_catalog.statement_timestamp() where id=new.purchase_id and renewal_canceled_at is null;
  return new;
end;
$function$;
revoke all on function billing.guard_annual_refund_request_v1(), billing.apply_annual_refund_request_v1()
  from public, anon, authenticated, service_role;
drop trigger if exists annual_refund_request_guard on billing.annual_refund_requests;
create trigger annual_refund_request_guard before insert or update or delete on billing.annual_refund_requests
  for each row execute function billing.guard_annual_refund_request_v1();
drop trigger if exists annual_refund_request_apply on billing.annual_refund_requests;
create trigger annual_refund_request_apply after insert on billing.annual_refund_requests
  for each row execute function billing.apply_annual_refund_request_v1();

drop policy if exists annual_refund_request_read on billing.annual_refund_requests;
create policy annual_refund_request_read on billing.annual_refund_requests for select to billing_store_owner using (
  public.company_access_has_fresh_mfa_v1() and (public.company_access_is_accepted_owner_v1(company_id)
    or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing')))
);
drop policy if exists annual_refund_request_insert on billing.annual_refund_requests;
create policy annual_refund_request_insert on billing.annual_refund_requests for insert to billing_store_owner with check (
  requested_by=public.company_access_auth_uid_v1() and public.company_access_has_fresh_mfa_v1()
  and (public.company_access_is_accepted_owner_v1(company_id)
    or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing')))
);
drop policy if exists annual_refund_request_bind on billing.annual_refund_requests;
create policy annual_refund_request_bind on billing.annual_refund_requests for update to billing_store_owner using (
  requested_by=public.company_access_auth_uid_v1() and public.company_access_has_fresh_mfa_v1()
  and (public.company_access_is_accepted_owner_v1(company_id)
    or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing')))
) with check (
  requested_by=public.company_access_auth_uid_v1() and public.company_access_has_fresh_mfa_v1()
  and (public.company_access_is_accepted_owner_v1(company_id)
    or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing')))
);
reset role;
do $references$
declare v_principal text := current_user; v_table text;
begin
  set local role billing_store_owner;
  foreach v_table in array pg_catalog.string_to_array(pg_catalog.current_setting('talli.annual_refund_requests_borrowed_references'), ',') loop
    execute pg_catalog.format('revoke references (id) on billing.%I from %I', v_table, v_principal);
  end loop;
  reset role;
end;
$references$;
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.annual_refund_requests_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.annual_refund_requests_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
