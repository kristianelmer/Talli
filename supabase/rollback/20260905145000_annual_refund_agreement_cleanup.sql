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
create or replace function billing.guard_annual_agreement_cleanup_v1()
returns trigger language plpgsql set search_path = '' as $function$
declare
  v_purchase billing.annual_purchases%rowtype;
  v_original billing.annual_operations%rowtype;
  v_receipt billing.annual_cancellation_requests%rowtype;
  v_intent jsonb := new.intent -> 'provider_intent';
  v_field text;
begin
  select * into v_purchase from billing.annual_purchases where id = new.purchase_id for update;
  if not found or v_purchase.company_id <> new.company_id or v_purchase.income_year <> new.income_year
    or v_purchase.renewal_canceled_at is null or v_purchase.agreement_reference is null
    or v_purchase.status = 'pending'
  then raise exception 'annual_cleanup_not_available'; end if;
  select * into v_original from billing.annual_operations
    where purchase_id = new.purchase_id and operation = 'checkout' for update;
  if not found or v_original.status not in ('confirmed','failed')
    or (v_purchase.status in ('paid','refunded') and
      (v_original.status <> 'confirmed' or v_purchase.captured_minor <> v_purchase.gross_minor))
    or (v_purchase.status = 'failed' and (v_original.status <> 'failed' or v_purchase.captured_minor <> 0))
  then raise exception 'annual_cleanup_not_available'; end if;
  select * into v_receipt from billing.annual_cancellation_requests
    where id = (new.intent ->> 'cancellation_id')::uuid
      and purchase_id = new.purchase_id and company_id = new.company_id and income_year = new.income_year;
  if not found or v_receipt.effective_at <> v_purchase.renewal_canceled_at
    or v_intent is null or pg_catalog.jsonb_typeof(v_intent) <> 'object'
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
drop function billing.annual_original_charge_resolved_v1(uuid);
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
