-- Allow the original refund-triggered renewal stop to drive agreement cleanup.
-- Exact receipt and terminal charge evidence remain separate requirements.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.annual_refund_cleanup_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.annual_refund_cleanup_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.annual_refund_cleanup_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role billing_store_owner;

-- The caller holds the purchase lock before inspecting original operation evidence.
-- Security invoker and forced RLS preserve the current verified-owner scope.
create or replace function billing.annual_original_charge_resolved_v1(p_purchase_id uuid)
returns boolean language sql stable set search_path = '' as $function$
  select exists (
    select 1 from billing.annual_purchases p
    join billing.annual_operations original on original.purchase_id=p.id and original.operation='checkout'
    where p.id=p_purchase_id and p.agreement_reference is not null
      and not exists (select 1 from billing.annual_operations unresolved where unresolved.purchase_id=p.id
        and (unresolved.operation='renewal' or (unresolved.operation='refund' and unresolved.status in ('created','pending','unknown'))))
      and not exists (select 1 from billing.annual_purchases other where other.id<>p.id
        and other.provider=p.provider and other.provider_account=p.provider_account
        and other.agreement_reference=p.agreement_reference)
      and (
        (p.status='failed' and p.captured_minor=0 and original.status='failed')
        or (p.status in ('paid','refunded') and p.captured_minor=p.gross_minor and original.status='confirmed')
        or (p.status='refunded' and p.captured_minor=p.gross_minor and p.refunded_minor=p.gross_minor
          and exists (
            select 1 from billing.annual_operations r
            where r.purchase_id=p.id and r.company_id=p.company_id and r.income_year=p.income_year
              and r.operation='refund' and r.status='confirmed'
              and r.intent ->> 'provider' = p.provider and r.intent ->> 'provider_account' = p.provider_account
              and r.intent -> 'provider_intent' ->> 'operation' = 'refund'
              and r.intent -> 'provider_intent' ->> 'operation_id' = r.id::text
              and r.intent -> 'provider_intent' ->> 'agreement_reference' = p.agreement_reference
              and r.intent -> 'provider_intent' -> 'amount_minor' = pg_catalog.to_jsonb(r.amount_minor)
              and r.amount_minor>0
              and pg_catalog.jsonb_typeof(r.intent -> 'captured_minor')='number'
              and (r.intent ->> 'captured_minor') ~ '^[0-9]+$'
              and (r.intent ->> 'captured_minor')::numeric between 1 and p.gross_minor
              and pg_catalog.jsonb_typeof(r.intent -> 'previous_refunded_minor')='number'
              and (r.intent ->> 'previous_refunded_minor') ~ '^[0-9]+$'
              and (r.intent ->> 'previous_refunded_minor')::numeric+r.amount_minor<=(r.intent ->> 'captured_minor')::numeric
              and (r.intent ->> 'captured_at')::timestamptz=p.captured_at
              and r.observation ->> 'provider'=p.provider
              and r.observation ->> 'operation'='refund' and r.observation ->> 'status'='confirmed'
              and r.observation ->> 'agreement_reference'=p.agreement_reference
              and r.observation ->> 'charge_reference'=p.charge_reference
              and (r.observation ->> 'amount_minor') ~ '^[0-9]+$'
              and (r.observation ->> 'captured_minor') ~ '^[0-9]+$'
              and (r.observation ->> 'refunded_minor') ~ '^[0-9]+$'
              and coalesce(r.observation -> 'checkout_url', 'null'::jsonb)='null'::jsonb
              and r.observation -> 'amount_minor'=pg_catalog.to_jsonb(r.amount_minor)
              and r.observation -> 'captured_minor'=pg_catalog.to_jsonb(p.gross_minor)
              and r.observation -> 'refunded_minor'=pg_catalog.to_jsonb(p.gross_minor)
              and (r.observation ->> 'captured_at')::timestamptz=p.captured_at
              and not exists (
                select 1 from pg_catalog.unnest(array['company_id','income_year','agreement_external_reference',
                  'charge_reference','return_url','management_url','recurring_consent',
                  'original_charge_minor','original_charge_is_renewal']) as field(name)
                where r.intent -> 'provider_intent' -> field.name is distinct from original.intent -> 'provider_intent' -> field.name
              )
          ))
      )
  );
$function$;
revoke all on function billing.annual_original_charge_resolved_v1(uuid) from public, anon, authenticated, service_role;

create or replace function billing.guard_annual_agreement_cleanup_v1()
returns trigger language plpgsql set search_path = '' as $function$
declare
  v_purchase billing.annual_purchases%rowtype;
  v_original billing.annual_operations%rowtype;
  v_stop_at timestamptz;
  v_intent jsonb := new.intent -> 'provider_intent';
  v_field text;
begin
  select * into v_purchase from billing.annual_purchases where id=new.purchase_id for update;
  if not found or v_purchase.company_id<>new.company_id or v_purchase.income_year<>new.income_year
    or v_purchase.renewal_canceled_at is null or not billing.annual_original_charge_resolved_v1(new.purchase_id)
  then raise exception 'annual_cleanup_not_available'; end if;
  select * into v_original from billing.annual_operations where purchase_id=new.purchase_id and operation='checkout' for update;
  if not found then raise exception 'annual_cleanup_not_available'; end if;
  -- A stop receipt and financial settlement evidence are independent requirements.
  if ((new.intent ->> 'cancellation_id') is null) = ((new.intent ->> 'refund_request_id') is null) then
    raise exception 'annual_cleanup_not_available';
  end if;
  if new.intent ->> 'cancellation_id' is not null then
    select effective_at into v_stop_at from billing.annual_cancellation_requests
      where id=(new.intent ->> 'cancellation_id')::uuid and purchase_id=new.purchase_id
        and company_id=new.company_id and income_year=new.income_year;
  else
    select requested_at into v_stop_at from billing.annual_refund_requests
      where id=(new.intent ->> 'refund_request_id')::uuid and purchase_id=new.purchase_id
        and company_id=new.company_id and income_year=new.income_year;
  end if;
  if v_stop_at is null or v_stop_at<>v_purchase.renewal_canceled_at
    or v_intent is null or pg_catalog.jsonb_typeof(v_intent)<>'object'
    or v_intent ->> 'operation' is distinct from 'stop_agreement'
    or v_intent -> 'amount_minor' is distinct from '0'::jsonb
    or v_intent ->> 'operation_id' is distinct from new.id::text
    or v_intent ->> 'agreement_reference' is distinct from v_purchase.agreement_reference
    or new.intent ->> 'provider' is distinct from v_purchase.provider
    or new.intent ->> 'provider_account' is distinct from v_purchase.provider_account
  then raise exception 'annual_cleanup_not_available'; end if;
  foreach v_field in array array['company_id','income_year','agreement_external_reference','charge_reference',
    'return_url','management_url','recurring_consent','original_charge_minor','original_charge_is_renewal'] loop
    if v_intent -> v_field is distinct from v_original.intent -> 'provider_intent' -> v_field then
      raise exception 'annual_cleanup_not_available';
    end if;
  end loop;
  return new;
end;
$function$;
revoke all on function billing.guard_annual_agreement_cleanup_v1() from public, anon, authenticated, service_role;
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.annual_refund_cleanup_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.annual_refund_cleanup_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
