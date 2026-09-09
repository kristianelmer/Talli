-- Explicit withdrawal of an unclaimed original request; never a cancellation.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.annual_checkout_withdrawals_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.annual_checkout_withdrawals_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.annual_checkout_withdrawals_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
do $restore$
begin
  if pg_catalog.to_regclass('billing.annual_checkout_withdrawals') is null
    and pg_catalog.to_regclass('billing_annual_retired.annual_checkout_withdrawals') is not null then
    alter table billing_annual_retired.annual_checkout_withdrawals set schema billing;
    alter function billing_annual_retired.guard_annual_checkout_request_v1() set schema billing;
  end if;
end;
$restore$;

create table if not exists billing.annual_checkout_withdrawals (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  requested_by uuid not null references auth.users(id) on delete restrict,
  requested_at timestamptz not null default pg_catalog.statement_timestamp(),
  idempotency_key text not null unique check (length(idempotency_key) between 8 and 200),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  offer_version text not null check (length(offer_version) between 1 and 100),
  terms_digest text not null check (terms_digest ~ '^[a-f0-9]{64}$'),
  purchase_accepted boolean not null check (purchase_accepted),
  recurring_consent boolean not null,
  consent_version text not null check (length(consent_version) between 1 and 100)
);
create index if not exists annual_checkout_withdrawal_company
  on billing.annual_checkout_withdrawals(company_id, income_year);
create index if not exists annual_checkout_withdrawal_actor
  on billing.annual_checkout_withdrawals(requested_by);
alter table billing.annual_checkout_withdrawals owner to billing_store_owner;
set local role billing_store_owner;
alter table billing.annual_checkout_withdrawals enable row level security;
alter table billing.annual_checkout_withdrawals force row level security;
revoke all on billing.annual_checkout_withdrawals from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
grant select, trigger on billing.annual_checkout_withdrawals to billing_store_owner;
-- RI key-share checks require one UPDATE column; no UPDATE policy exists and
-- the immutable trigger rejects changes. This does not permit receipt editing.
grant update (id) on billing.annual_checkout_withdrawals to billing_store_owner;
grant insert (company_id,income_year,requested_by,idempotency_key,request_fingerprint,
  offer_version,terms_digest,purchase_accepted,recurring_consent,consent_version)
  on billing.annual_checkout_withdrawals to billing_store_owner;
drop policy if exists annual_checkout_withdrawal_read on billing.annual_checkout_withdrawals;
create policy annual_checkout_withdrawal_read on billing.annual_checkout_withdrawals
  for select to billing_store_owner using (
    public.company_access_has_fresh_mfa_v1() and public.company_access_is_accepted_owner_v1(company_id)
  );
drop policy if exists annual_checkout_withdrawal_insert on billing.annual_checkout_withdrawals;
create policy annual_checkout_withdrawal_insert on billing.annual_checkout_withdrawals
  for insert to billing_store_owner with check (
    requested_by = public.company_access_auth_uid_v1()
    and public.company_access_has_fresh_mfa_v1() and public.company_access_is_accepted_owner_v1(company_id)
  );

create or replace function billing.guard_annual_checkout_request_v1()
returns trigger language plpgsql security invoker set search_path = '' as $function$
begin
  if tg_op <> 'INSERT' then raise exception 'annual_checkout_withdrawal_is_immutable'; end if;
  if tg_table_name = 'annual_operations' then
    if new.operation <> 'checkout' then return new; end if;
  end if;
  -- Shared across years. A separate unique index in each table cannot serialize
  -- a changed-year retry against its original request in the other table.
  -- The current adapter already holds both locks and reauthorizes using separate
  -- statements after waits. Older writers/direct SQL must retry on contention:
  -- a trigger must not wait while the MFA predicate's statement clock stands still.
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended('annual-checkout-key|' || new.idempotency_key, 192)) then
    raise lock_not_available using message = 'annual_checkout_request_busy';
  end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'annual-checkout|' || new.company_id::text || '|' || new.income_year::text, 192)) then
    raise lock_not_available using message = 'annual_checkout_request_busy';
  end if;
  -- Hidden forced-RLS evidence must never become authority for a new outcome.
  if not public.company_access_is_accepted_owner_v1(new.company_id)
    or not public.company_access_has_fresh_mfa_v1() then
    raise insufficient_privilege using message = 'annual_checkout_owner_required';
  end if;
  if tg_table_name = 'annual_operations' then
    if exists (select 1 from billing.annual_checkout_withdrawals
      where company_id = new.company_id and idempotency_key = new.idempotency_key) then
      raise exception 'annual_checkout_request_withdrawn';
    end if;
  else
    if exists (select 1 from billing.annual_operations
      where company_id = new.company_id and idempotency_key = new.idempotency_key and operation = 'checkout') then
      raise unique_violation using message = 'annual_checkout_already_claimed';
    end if;
    new.requested_at := pg_catalog.statement_timestamp();
  end if;
  return new;
end;
$function$;
revoke all on function billing.guard_annual_checkout_request_v1() from public, anon, authenticated, service_role;
drop trigger if exists annual_checkout_request_fence on billing.annual_operations;
create trigger annual_checkout_request_fence before insert on billing.annual_operations
  for each row execute function billing.guard_annual_checkout_request_v1();
drop trigger if exists annual_checkout_withdrawal_fence on billing.annual_checkout_withdrawals;
create trigger annual_checkout_withdrawal_fence before insert or update or delete on billing.annual_checkout_withdrawals
  for each row execute function billing.guard_annual_checkout_request_v1();
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.annual_checkout_withdrawals_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.annual_checkout_withdrawals_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
