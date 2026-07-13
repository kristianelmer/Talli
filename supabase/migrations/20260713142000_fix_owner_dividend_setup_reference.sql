-- PostgreSQL treats PL/pgSQL variables and unqualified column references as
-- ambiguous when they share a name. Rename the local setup identifier so the
-- shareholder-register checks execute consistently on PostgreSQL 17.

create or replace function public.record_owner_dividend_action(
  p_company_id uuid,
  p_income_year integer,
  p_ledger_entry_id uuid,
  p_action_id uuid,
  p_payload jsonb,
  p_documents jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  total_amount numeric;
  distributable_equity numeric;
  liquidity_after_payment numeric;
  allocation_total numeric;
  allocation_count integer;
  allocation_share_count numeric;
  registered_shareholder_count integer;
  registered_share_count numeric;
  valid_allocation_count integer;
  opening_setup_id uuid;
  document_count integer;
  valid_document_count integer;
begin
  if actor_id is null then
    raise exception 'authentication required';
  end if;
  if p_income_year < 2000 or p_income_year > 2100 then
    raise exception 'invalid income year';
  end if;
  if jsonb_typeof(p_payload) <> 'object'
    or jsonb_typeof(p_payload -> 'allocations') <> 'array'
    or jsonb_array_length(p_payload -> 'allocations') = 0
    or p_payload ->> 'document_status' <> 'attached'
  then
    raise exception 'invalid owner dividend payload';
  end if;

  total_amount := (p_payload ->> 'total_amount')::numeric;
  distributable_equity := (p_payload ->> 'distributable_equity')::numeric;
  liquidity_after_payment := (p_payload ->> 'liquidity_after_payment')::numeric;
  select coalesce(sum((allocation ->> 'amount')::numeric), 0)
  into allocation_total
  from jsonb_array_elements(p_payload -> 'allocations') allocation;
  if total_amount <= 0
    or total_amount > distributable_equity
    or liquidity_after_payment < 0
    or allocation_total <> total_amount
  then
    raise exception 'owner dividend amount validation failed';
  end if;

  select setup.id, setup.share_count
  into opening_setup_id, registered_share_count
  from public.opening_balance_setups setup
  where setup.company_id = p_company_id
    and setup.income_year = p_income_year;
  if opening_setup_id is null then
    raise exception 'owner dividend requires an opening shareholder register';
  end if;
  allocation_count := jsonb_array_length(p_payload -> 'allocations');
  select coalesce(sum((allocation ->> 'shareCount')::numeric), 0)
  into allocation_share_count
  from jsonb_array_elements(p_payload -> 'allocations') allocation;
  select count(distinct shareholder.id)
  into registered_shareholder_count
  from public.opening_shareholders shareholder
  where shareholder.setup_id = opening_setup_id;
  select count(distinct shareholder.id)
  into valid_allocation_count
  from jsonb_array_elements(p_payload -> 'allocations') allocation
  join public.opening_shareholders shareholder
    on shareholder.id = (allocation ->> 'shareholderId')::uuid
   and shareholder.setup_id = opening_setup_id
  where shareholder.name = allocation ->> 'shareholderName'
    and shareholder.share_count = (allocation ->> 'shareCount')::numeric
    and (allocation ->> 'amount')::numeric * registered_share_count
      = total_amount * shareholder.share_count;
  if allocation_count <> registered_shareholder_count
    or allocation_count <> valid_allocation_count
    or allocation_share_count <> registered_share_count
  then
    raise exception 'owner dividend must include the complete register at an equal amount per share';
  end if;

  if jsonb_typeof(p_documents) <> 'array' then
    raise exception 'invalid owner dividend documents';
  end if;
  document_count := jsonb_array_length(p_documents);
  select count(*)
  into valid_document_count
  from jsonb_array_elements(p_documents) document
  where document ->> 'name' in (
      'styreforslag-og-protokoll-utbytte.pdf',
      'generalforsamlingsprotokoll-utbytte.pdf'
    )
    and document ->> 'storage_key' like (
      p_company_id::text || '/' || p_income_year::text || '/' || (document ->> 'id') || '/%'
    )
    and exists (
      select 1
      from storage.objects object
      where object.bucket_id = 'company-documents'
        and object.name = (document ->> 'storage_key')
        and object.metadata ->> 'mimetype' = 'application/pdf'
        and coalesce((object.metadata ->> 'size')::bigint, 0) between 1 and 6291456
    );
  if document_count <> 2
    or valid_document_count <> 2
    or (
      select count(distinct document ->> 'name')
      from jsonb_array_elements(p_documents) document
    ) <> 2
  then
    raise exception 'owner dividend requires two valid PDF records';
  end if;

  insert into public.ledger_entries (
    id,
    company_id,
    income_year,
    entry_type,
    memo,
    lines,
    risk_flags,
    created_by
  )
  values (
    p_ledger_entry_id,
    p_company_id,
    p_income_year,
    'dividend_to_owner',
    'Cash dividend paid to shareholders',
    jsonb_build_array(
      jsonb_build_object(
        'account', '2050',
        'description', 'Dividend to shareholders',
        'debit', total_amount,
        'credit', 0
      ),
      jsonb_build_object(
        'account', '1920',
        'description', 'Dividend paid from bank',
        'debit', 0,
        'credit', total_amount
      )
    ),
    '[]'::jsonb,
    actor_id
  );

  insert into public.holding_actions (
    id,
    company_id,
    income_year,
    action_type,
    action_date,
    payload,
    ledger_entry_id,
    risk_level,
    created_by
  )
  values (
    p_action_id,
    p_company_id,
    p_income_year,
    'dividend_to_owner',
    (p_payload ->> 'payment_date')::date,
    p_payload,
    p_ledger_entry_id,
    'ready',
    actor_id
  );

  insert into public.documents (
    id,
    company_id,
    income_year,
    document_type,
    name,
    linked_to,
    status,
    retention_years,
    storage_key,
    created_by
  )
  select
    (document ->> 'id')::uuid,
    p_company_id,
    p_income_year,
    'corporate_document',
    document ->> 'name',
    p_action_id::text,
    'generated_unsigned',
    5,
    document ->> 'storage_key',
    actor_id
  from jsonb_array_elements(p_documents) document;

  return jsonb_build_object('ledger_entry_id', p_ledger_entry_id, 'action_id', p_action_id);
end;
$$;

revoke all on function public.record_owner_dividend_action(uuid, integer, uuid, uuid, jsonb, jsonb)
from public, anon;
grant execute on function public.record_owner_dividend_action(uuid, integer, uuid, uuid, jsonb, jsonb)
to authenticated;
