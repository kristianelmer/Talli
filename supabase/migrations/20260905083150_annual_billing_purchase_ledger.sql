-- Annual billing evidence and durable provider claims. No provider is activated.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner, company_access_executor to %I', current_user);
end;
$borrow$;

set local role company_access_executor;
grant execute on function public.company_access_current_support_case_id_v1(),
  public.company_access_has_open_support_case_v1(uuid, uuid, text) to billing_store_owner;
reset role;
create schema if not exists billing_annual_retired authorization billing_store_owner;
revoke all on schema billing_annual_retired from public, anon, authenticated, service_role, billing_executor;

-- Recutover restores the same records, including unresolved provider effects.
do $restore$
declare v_name text;
begin
  foreach v_name in array array['annual_purchases', 'annual_refund_cases', 'annual_operations'] loop
    if pg_catalog.to_regclass('billing.' || v_name) is null
      and pg_catalog.to_regclass('billing_annual_retired.' || v_name) is not null then
      execute pg_catalog.format('alter table billing_annual_retired.%I set schema billing', v_name);
    end if;
  end loop;
end;
$restore$;

create table if not exists billing.annual_purchases (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  accepted_by uuid not null references auth.users(id) on delete restrict,
  accepted_at timestamptz not null default pg_catalog.statement_timestamp(),
  offer_version text not null check (length(offer_version) between 1 and 100),
  terms_digest text not null check (terms_digest ~ '^[a-f0-9]{64}$'),
  terms_text text not null check (length(terms_text) between 1 and 20000),
  currency text not null check (currency = 'NOK'),
  gross_minor integer not null check (gross_minor > 0),
  net_minor integer not null check (net_minor > 0),
  vat_minor integer not null check (vat_minor > 0),
  vat_basis_points integer not null check (vat_basis_points = 2500),
  paid_through date not null,
  export_through date not null check (export_through >= paid_through + 90),
  renewal_date date not null,
  accepted_basis jsonb not null check (jsonb_typeof(accepted_basis) = 'object' and octet_length(accepted_basis::text) <= 65536),
  recurring_consent boolean not null,
  consent_version text not null check (length(consent_version) between 1 and 100),
  provider text not null check (length(provider) between 1 and 100),
  provider_account text not null check (length(provider_account) between 1 and 100),
  agreement_external_reference text not null check (length(agreement_external_reference) between 1 and 64),
  charge_reference text not null check (charge_reference ~ '^[A-Za-z0-9-]{1,64}$'),
  status text not null default 'pending' check (status in ('pending', 'paid', 'failed', 'refunded')),
  agreement_reference text,
  captured_minor integer not null default 0 check (captured_minor >= 0),
  refunded_minor integer not null default 0 check (refunded_minor >= 0),
  captured_at timestamptz,
  renewal_canceled_at timestamptz,
  updated_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (id, company_id, income_year),
  unique (provider, provider_account, agreement_external_reference),
  unique (provider, provider_account, charge_reference),
  check (gross_minor = net_minor + vat_minor and vat_minor = (gross_minor + 2) / 5),
  check (terms_digest = pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(terms_text, 'UTF8')), 'hex')),
  check (refunded_minor <= captured_minor and captured_minor <= gross_minor),
  check ((captured_minor = 0) = (captured_at is null)),
  check (status <> 'paid' or captured_minor = gross_minor),
  check (status <> 'failed' or captured_minor = 0),
  check (status <> 'refunded' or (captured_minor > 0 and captured_minor = refunded_minor))
);
drop index if exists billing.annual_one_open_purchase_per_company_year;
create unique index annual_one_open_purchase_per_company_year
  on billing.annual_purchases(company_id, income_year) where status in ('pending', 'paid');

create table if not exists billing.annual_refund_cases (
  id uuid primary key,
  purchase_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  reason text not null check (reason in ('change_of_mind', 'talli_acceptance_failure', 'talli_delivery_failure', 'new_unsupported_condition', 'customer_unresolved')),
  source_reference text not null check (length(source_reference) between 1 and 1000),
  facts jsonb not null check (jsonb_typeof(facts) = 'object' and octet_length(facts::text) <= 65536),
  total_entitlement_minor integer not null check (total_entitlement_minor >= 0),
  initiate_by date not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (id, purchase_id, company_id, income_year),
  unique (purchase_id, source_reference),
  foreign key (purchase_id, company_id, income_year)
    references billing.annual_purchases(id, company_id, income_year) on delete restrict
);

create table if not exists billing.annual_operations (
  id uuid primary key,
  purchase_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  idempotency_key text not null unique check (length(idempotency_key) between 8 and 200),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  operation text not null check (operation in ('checkout', 'renewal', 'stop_agreement', 'cancel_charge', 'refund')),
  amount_minor integer not null check (amount_minor >= 0),
  intent jsonb not null check (jsonb_typeof(intent) = 'object' and octet_length(intent::text) <= 65536),
  refund_case_id uuid,
  status text not null default 'created' check (status in ('created', 'pending', 'unknown', 'confirmed', 'failed')),
  observation jsonb check (observation is null or (jsonb_typeof(observation) = 'object' and octet_length(observation::text) <= 65536)),
  updated_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (purchase_id, company_id, income_year)
    references billing.annual_purchases(id, company_id, income_year) on delete restrict,
  foreign key (refund_case_id, purchase_id, company_id, income_year)
    references billing.annual_refund_cases(id, purchase_id, company_id, income_year) on delete restrict,
  check ((operation = 'refund') = (refund_case_id is not null)),
  check (operation not in ('stop_agreement', 'cancel_charge') or amount_minor = 0),
  check (operation not in ('checkout', 'renewal', 'refund') or amount_minor > 0)
);
create unique index if not exists annual_one_charge_per_purchase
  on billing.annual_operations(purchase_id) where operation in ('checkout', 'renewal');
create unique index if not exists annual_one_unresolved_refund_per_purchase
  on billing.annual_operations(purchase_id) where operation = 'refund' and status in ('created', 'pending', 'unknown');
create index if not exists annual_operation_company_year on billing.annual_operations(company_id, income_year, created_at);
create index if not exists annual_refund_case_company_year on billing.annual_refund_cases(company_id, income_year, created_at);
create index if not exists annual_purchase_actor on billing.annual_purchases(accepted_by);
create index if not exists annual_operation_actor on billing.annual_operations(created_by);
create index if not exists annual_operation_purchase on billing.annual_operations(purchase_id);
create index if not exists annual_operation_refund_case on billing.annual_operations(refund_case_id, purchase_id, company_id, income_year);
create index if not exists annual_refund_case_actor on billing.annual_refund_cases(created_by);

alter table billing.annual_purchases owner to billing_store_owner;
alter table billing.annual_operations owner to billing_store_owner;
alter table billing.annual_refund_cases owner to billing_store_owner;
set local role billing_store_owner;

create or replace function billing.guard_annual_evidence_v1()
returns trigger language plpgsql set search_path = '' as $function$
begin
  if tg_op = 'DELETE' then raise exception 'annual_evidence_is_immutable'; end if;
  if tg_table_name = 'annual_purchases' then
    if (pg_catalog.to_jsonb(new) - array['status','agreement_reference','captured_minor','refunded_minor','captured_at','renewal_canceled_at','updated_at'])
      is distinct from (pg_catalog.to_jsonb(old) - array['status','agreement_reference','captured_minor','refunded_minor','captured_at','renewal_canceled_at','updated_at'])
      or new.captured_minor < old.captured_minor or new.refunded_minor < old.refunded_minor
      or (old.agreement_reference is not null and new.agreement_reference is distinct from old.agreement_reference)
      or (old.captured_at is not null and new.captured_at is distinct from old.captured_at)
      or (old.renewal_canceled_at is not null and new.renewal_canceled_at is distinct from old.renewal_canceled_at)
      or (old.status in ('failed', 'refunded') and new.status <> old.status)
    then raise exception 'annual_evidence_is_immutable'; end if;
  elsif tg_table_name = 'annual_operations' then
    if (pg_catalog.to_jsonb(new) - array['status','observation','updated_at'])
      is distinct from (pg_catalog.to_jsonb(old) - array['status','observation','updated_at'])
      or (old.status in ('confirmed', 'failed') and pg_catalog.to_jsonb(new) is distinct from pg_catalog.to_jsonb(old))
    then raise exception 'annual_evidence_is_immutable'; end if;
  else
    raise exception 'annual_evidence_is_immutable';
  end if;
  return new;
end;
$function$;

create or replace function billing.reserve_annual_operation_v1()
returns trigger language plpgsql set search_path = '' as $function$
declare v_purchase billing.annual_purchases%rowtype; v_existing billing.annual_operations%rowtype; v_entitlement integer; v_reserved bigint;
begin
  -- This lock is shared by settlement and cancellation, and precedes op locks.
  select * into v_purchase from billing.annual_purchases where id = new.purchase_id for update;
  if not found or v_purchase.company_id <> new.company_id or v_purchase.income_year <> new.income_year then
    raise exception 'annual_purchase_not_available';
  end if;
  -- Recheck after the purchase lock so concurrent retries observe the winner.
  select * into v_existing from billing.annual_operations where idempotency_key = new.idempotency_key;
  if found then
    if v_existing.company_id <> new.company_id or v_existing.purchase_id <> new.purchase_id
      or v_existing.request_fingerprint <> new.request_fingerprint
      or v_existing.operation <> new.operation or v_existing.amount_minor <> new.amount_minor
    then raise exception 'annual_idempotency_key_reused'; end if;
    return new;
  end if;
  if new.operation in ('checkout', 'renewal') then
    if v_purchase.status <> 'pending' or new.amount_minor <> v_purchase.gross_minor
      or (new.operation = 'renewal' and (not v_purchase.recurring_consent or v_purchase.renewal_canceled_at is not null))
    then raise exception 'annual_payment_not_allowed'; end if;
  elsif new.operation = 'refund' then
    select total_entitlement_minor into v_entitlement from billing.annual_refund_cases
      where id = new.refund_case_id and purchase_id = new.purchase_id;
    select coalesce(sum(amount_minor), 0) into v_reserved from billing.annual_operations
      where purchase_id = new.purchase_id and operation = 'refund'
        and status in ('created', 'pending', 'unknown');
    if v_entitlement is null or new.amount_minor > least(v_entitlement, v_purchase.captured_minor) - v_purchase.refunded_minor - v_reserved then
      raise exception 'annual_refund_not_available';
    end if;
  end if;
  return new;
end;
$function$;
revoke all on function billing.guard_annual_evidence_v1(), billing.reserve_annual_operation_v1()
  from public, anon, authenticated, service_role;

do $policies$
declare v_name text;
begin
  foreach v_name in array array['annual_purchases', 'annual_refund_cases', 'annual_operations'] loop
    execute pg_catalog.format('alter table billing.%I enable row level security', v_name);
    execute pg_catalog.format('alter table billing.%I force row level security', v_name);
    execute pg_catalog.format('revoke all on billing.%I from public, anon, authenticated, service_role, billing_executor, billing_store_owner', v_name);
    execute pg_catalog.format('grant select on billing.%I to billing_executor, billing_store_owner', v_name);
    execute pg_catalog.format('grant insert, trigger on billing.%I to billing_store_owner', v_name);
    execute pg_catalog.format('drop policy if exists annual_member_read on billing.%I', v_name);
    execute pg_catalog.format('create policy annual_member_read on billing.%I for select to billing_executor using (public.company_access_is_accepted_member_v1(company_id))', v_name);
    execute pg_catalog.format('drop policy if exists annual_owner_operator_read on billing.%I', v_name);
    execute pg_catalog.format('create policy annual_owner_operator_read on billing.%I for select to billing_store_owner using (public.company_access_has_fresh_mfa_v1() and (public.company_access_is_accepted_owner_v1(company_id) or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, ''billing''))))', v_name);
    execute pg_catalog.format('drop trigger if exists annual_evidence_immutable on billing.%I', v_name);
    execute pg_catalog.format('create trigger annual_evidence_immutable before update or delete on billing.%I for each row execute function billing.guard_annual_evidence_v1()', v_name);
  end loop;
end;
$policies$;

-- PostgreSQL's referential-integrity key-share check requires UPDATE privilege
-- on one column. No UPDATE policy exists, and the immutable trigger rejects it.
grant update (id) on billing.annual_refund_cases to billing_store_owner;

drop policy if exists annual_purchase_claim on billing.annual_purchases;
create policy annual_purchase_claim on billing.annual_purchases for insert to billing_store_owner
with check (
  accepted_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
  and status = 'pending' and captured_minor = 0 and refunded_minor = 0
  and accepted_basis = public.company_access_purchase_basis_v1(company_id, income_year,
    (accepted_basis ->> 'assessment_id')::uuid, (accepted_basis -> 'legal_evidence' ->> 'id')::uuid)
);
drop policy if exists annual_refund_case_claim on billing.annual_refund_cases;
create policy annual_refund_case_claim on billing.annual_refund_cases for insert to billing_store_owner
with check (
  created_by = public.company_access_auth_uid_v1() and public.company_access_has_fresh_mfa_v1()
  and ((reason = 'change_of_mind' and public.company_access_is_accepted_owner_v1(company_id))
    or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing')))
);
drop policy if exists annual_operation_claim on billing.annual_operations;
create policy annual_operation_claim on billing.annual_operations for insert to billing_store_owner
with check (
  created_by = public.company_access_auth_uid_v1() and public.company_access_has_fresh_mfa_v1()
  and status = 'created' and observation is null
  and (public.company_access_is_accepted_owner_v1(company_id)
    or (operation in ('refund','stop_agreement','cancel_charge') and (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, 'billing'))))
);
drop trigger if exists annual_operation_reservation on billing.annual_operations;
create trigger annual_operation_reservation before insert on billing.annual_operations
for each row execute function billing.reserve_annual_operation_v1();

do $settlement$
declare v_name text;
begin
  foreach v_name in array array['annual_purchases', 'annual_operations'] loop
    execute pg_catalog.format('grant update on billing.%I to billing_store_owner', v_name);
    execute pg_catalog.format('drop policy if exists annual_settle on billing.%I', v_name);
    execute pg_catalog.format('create policy annual_settle on billing.%I for update to billing_store_owner using (public.company_access_has_fresh_mfa_v1() and (public.company_access_is_accepted_owner_v1(company_id) or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, ''billing'')))) with check (public.company_access_has_fresh_mfa_v1() and (public.company_access_is_accepted_owner_v1(company_id) or (public.company_access_is_active_admin_v1() and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(), company_id, ''billing''))))', v_name);
  end loop;
end;
$settlement$;
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner, company_access_executor from %I', current_user);
end;
$return_authority$;
commit;
