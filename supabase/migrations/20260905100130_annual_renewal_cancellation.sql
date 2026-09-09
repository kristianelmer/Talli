-- Durable owner-requested renewal cancellation. Provider cleanup is separate.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end;
$borrow$;
do $references$
declare v_principal text := current_user; v_column text; v_missing text[] := array[]::text[];
begin
  foreach v_column in array array['id','company_id','income_year'] loop
    if not pg_catalog.has_column_privilege(v_principal, 'billing.annual_purchases', v_column, 'REFERENCES') then
      v_missing := pg_catalog.array_append(v_missing, v_column);
    end if;
  end loop;
  perform pg_catalog.set_config('talli.cancellation_borrowed_references', pg_catalog.array_to_string(v_missing, ','), true);
  set local role billing_store_owner;
  foreach v_column in array v_missing loop
    execute pg_catalog.format('grant references (%I) on billing.annual_purchases to %I', v_column, v_principal);
  end loop;
  reset role;
end;
$references$;

do $restore$
begin
  if pg_catalog.to_regclass('billing.annual_cancellation_requests') is null
    and pg_catalog.to_regclass('billing_annual_retired.annual_cancellation_requests') is not null then
    alter table billing_annual_retired.annual_cancellation_requests set schema billing;
  end if;
end;
$restore$;

create table if not exists billing.annual_cancellation_requests (
  id uuid primary key,
  purchase_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  requested_by uuid not null references auth.users(id) on delete restrict,
  requested_at timestamptz not null default pg_catalog.statement_timestamp(),
  effective_at timestamptz not null,
  idempotency_key text not null unique check (length(idempotency_key) between 8 and 200),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  scope text not null default 'stop_renewal' check (scope = 'stop_renewal'),
  foreign key (purchase_id, company_id, income_year)
    references billing.annual_purchases(id, company_id, income_year) on delete restrict
);
create index if not exists annual_cancellation_purchase
  on billing.annual_cancellation_requests(purchase_id, company_id, income_year);
create index if not exists annual_cancellation_actor
  on billing.annual_cancellation_requests(requested_by);
alter table billing.annual_cancellation_requests owner to billing_store_owner;
set local role billing_store_owner;
alter table billing.annual_cancellation_requests enable row level security;
alter table billing.annual_cancellation_requests force row level security;
revoke all on billing.annual_cancellation_requests from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
grant select, insert, trigger on billing.annual_cancellation_requests to billing_store_owner;
-- Referential-integrity FOR KEY SHARE requires UPDATE on one column. No UPDATE
-- policy exists; immutable triggers also reject any evidence mutation.
grant update (id) on billing.annual_cancellation_requests to billing_store_owner;

create or replace function billing.apply_annual_cancellation_request_v1()
returns trigger language plpgsql set search_path = '' as $function$
declare v_purchase billing.annual_purchases%rowtype;
begin
  -- Invoker permissions and forced RLS apply. No eligibility/readiness predicate:
  -- a later support block cannot obstruct stopping future renewal.
  select * into v_purchase from billing.annual_purchases where id = new.purchase_id for update;
  if not found or v_purchase.company_id <> new.company_id or v_purchase.income_year <> new.income_year then
    raise exception 'annual_purchase_not_available';
  end if;
  new.effective_at := coalesce(v_purchase.renewal_canceled_at, pg_catalog.statement_timestamp());
  new.requested_at := pg_catalog.statement_timestamp();
  -- Only the AFTER trigger may mutate the purchase: BEFORE INSERT also runs
  -- when ON CONFLICT skips the receipt. Never stop renewal without a receipt.
  if tg_when = 'AFTER' and v_purchase.renewal_canceled_at is null then
    update billing.annual_purchases set renewal_canceled_at = new.effective_at,
      updated_at = pg_catalog.statement_timestamp() where id = new.purchase_id;
  end if;
  return new;
end;
$function$;
revoke all on function billing.apply_annual_cancellation_request_v1() from public, anon, authenticated, service_role;
drop trigger if exists annual_cancellation_prepare on billing.annual_cancellation_requests;
create trigger annual_cancellation_prepare before insert on billing.annual_cancellation_requests
  for each row execute function billing.apply_annual_cancellation_request_v1();
drop trigger if exists annual_cancellation_apply on billing.annual_cancellation_requests;
create trigger annual_cancellation_apply after insert on billing.annual_cancellation_requests
  for each row execute function billing.apply_annual_cancellation_request_v1();
drop trigger if exists annual_cancellation_immutable on billing.annual_cancellation_requests;
create trigger annual_cancellation_immutable before update or delete on billing.annual_cancellation_requests
  for each row execute function billing.guard_annual_evidence_v1();
drop policy if exists annual_cancellation_owner_read on billing.annual_cancellation_requests;
create policy annual_cancellation_owner_read on billing.annual_cancellation_requests
  for select to billing_store_owner using (
    public.company_access_has_fresh_mfa_v1() and public.company_access_is_accepted_owner_v1(company_id)
  );
drop policy if exists annual_cancellation_owner_request on billing.annual_cancellation_requests;
create policy annual_cancellation_owner_request on billing.annual_cancellation_requests
  for insert to billing_store_owner with check (
    requested_by = public.company_access_auth_uid_v1()
    and public.company_access_has_fresh_mfa_v1() and public.company_access_is_accepted_owner_v1(company_id)
  );
reset role;
do $references$
declare v_principal text := current_user; v_column text;
begin
  set local role billing_store_owner;
  foreach v_column in array pg_catalog.string_to_array(pg_catalog.current_setting('talli.cancellation_borrowed_references'), ',') loop
    execute pg_catalog.format('revoke references (%I) on billing.annual_purchases from %I', v_column, v_principal);
  end loop;
  reset role;
end;
$references$;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end;
$return_authority$;
commit;
