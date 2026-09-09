-- Guard one receipt-bound original-agreement stop. No provider is activated.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end;
$borrow$;
set local role billing_store_owner;
create unique index if not exists annual_one_agreement_cleanup_per_purchase
  on billing.annual_operations(purchase_id) where operation = 'stop_agreement';

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
drop trigger if exists annual_cleanup_claim_guard on billing.annual_operations;
create trigger annual_cleanup_claim_guard before insert on billing.annual_operations
  for each row when (new.operation = 'stop_agreement')
  execute function billing.guard_annual_agreement_cleanup_v1();
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end;
$return_authority$;
commit;
