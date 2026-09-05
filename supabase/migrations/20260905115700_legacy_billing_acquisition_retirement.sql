-- Retire legacy acquisition even while an older backend binary is draining.
-- Historical events and cleanup remain available; annual authority is separate.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.legacy_retirement_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.legacy_retirement_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.legacy_retirement_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role billing_store_owner;
lock table billing.billing_accounts, billing.billing_payment_events in share row exclusive mode;

create or replace function billing.guard_legacy_account_retirement_v1()
returns trigger language plpgsql set search_path = '' as $function$
begin
  if tg_op = 'INSERT' then
    raise exception 'billing_legacy_acquisition_retired';
  end if;
  if row(new.company_id, new.pricing_plan, new.monthly_nok, new.filing_package_nok,
         new.founder_cohort_number, new.created_at)
    is distinct from
     row(old.company_id, old.pricing_plan, old.monthly_nok, old.filing_package_nok,
         old.founder_cohort_number, old.created_at)
    or (not old.subscription_active and new.subscription_active)
    or (not old.filing_package_paid and new.filing_package_paid)
    or (not old.supported_case and new.supported_case)
    or (old.refund_completed and not new.refund_completed)
  then raise exception 'billing_legacy_acquisition_retired'; end if;
  return new;
end;
$function$;
revoke all on function billing.guard_legacy_account_retirement_v1() from public, anon, authenticated, service_role;
drop trigger if exists legacy_account_retirement on billing.billing_accounts;
create trigger legacy_account_retirement before insert or update on billing.billing_accounts
for each row execute function billing.guard_legacy_account_retirement_v1();

create or replace function billing.guard_legacy_event_retirement_v1()
returns trigger language plpgsql set search_path = '' as $function$
begin
  if tg_op = 'INSERT' then
    if new.kind in ('subscription', 'filing_package') then
      raise exception 'billing_legacy_acquisition_retired';
    end if;
  else
    if row(new.id, new.company_id, new.provider, new.idempotency_key, new.kind,
           new.amount_nok, new.income_year, new.created_by, new.created_at)
      is distinct from
       row(old.id, old.company_id, old.provider, old.idempotency_key, old.kind,
           old.amount_nok, old.income_year, old.created_by, old.created_at)
      or (old.kind = 'filing_package' and
        coalesce(new.payload ->> 'obligation', 'aksjonaerregisteroppgaven') is distinct from
        coalesce(old.payload ->> 'obligation', 'aksjonaerregisteroppgaven'))
      or (old.status in ('succeeded', 'refunded', 'canceled') and new is distinct from old)
    then raise exception 'billing_legacy_event_identity_immutable'; end if;
  end if;
  if (new.kind in ('subscription', 'filing_package') and new.status not in ('created', 'failed', 'succeeded'))
    or (new.kind = 'subscription_cancellation' and new.status not in ('created', 'failed', 'canceled'))
    or (new.kind = 'refund' and new.status not in ('created', 'failed', 'refunded'))
  then raise exception 'billing_legacy_event_status_invalid'; end if;
  return new;
end;
$function$;
revoke all on function billing.guard_legacy_event_retirement_v1() from public, anon, authenticated, service_role;
drop trigger if exists legacy_event_retirement on billing.billing_payment_events;
create trigger legacy_event_retirement before insert or update on billing.billing_payment_events
for each row execute function billing.guard_legacy_event_retirement_v1();
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.legacy_retirement_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.legacy_retirement_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
