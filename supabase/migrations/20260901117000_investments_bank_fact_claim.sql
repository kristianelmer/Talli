-- Let the investments lifecycle atomically claim its canonical banking fact.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant banking_store_owner, investments_workflow_executor to %I',
    current_user
  );
end
$membership$;

grant usage, create on schema banking to banking_store_owner;

set local role banking_store_owner;

create or replace function banking.claim_transaction_for_external_action_v1(
  p_request jsonb,
  p_accounting_entry_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid;
  v_income_year integer;
  v_transaction_id uuid;
  v_transaction_date date;
  v_signed_amount numeric(20, 2);
  v_source_hash text;
  v_action_reference text;
  v_transaction banking.transactions%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'banking_forbidden';
  end if;

  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_transaction_id := (p_request ->> 'transactionId')::uuid;
    v_transaction_date := (p_request ->> 'transactionDate')::date;
    v_signed_amount := (p_request ->> 'signedAmount')::numeric(20, 2);
    v_source_hash := pg_catalog.lower(
      pg_catalog.btrim(p_request ->> 'sourceHash')
    );
    v_action_reference := pg_catalog.btrim(
      p_request ->> 'actionReference'
    );
  exception when others then
    raise exception 'banking_invalid_input';
  end;

  if p_accounting_entry_id is null
    or v_income_year < 2000 or v_income_year > 2100
    or v_transaction_date < pg_catalog.make_date(v_income_year, 1, 1)
    or v_transaction_date > pg_catalog.make_date(v_income_year, 12, 31)
    or v_source_hash !~ '^[0-9a-f]{64}$'
    or v_action_reference = ''
    or pg_catalog.char_length(v_action_reference) > 255
  then
    raise exception 'banking_invalid_input';
  end if;

  if not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'banking_forbidden';
  end if;

  perform ledger.lock_company_year_v1(v_company_id, v_income_year);
  if coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then
    raise exception 'banking_company_year_not_admitted';
  end if;

  select bank_row.*
  into v_transaction
  from banking.transactions bank_row
  where bank_row.id = v_transaction_id
    and bank_row.company_id = v_company_id
    and bank_row.income_year = v_income_year
  for update;

  if not found then
    raise exception 'banking_transaction_not_found';
  end if;
  if v_transaction.matched_accounting_entry_id is not null
    or v_transaction.matched_action_reference is not null
    or v_transaction.warning_accepted
  then
    raise exception 'banking_transaction_already_reconciled';
  end if;
  if v_transaction.transaction_date <> v_transaction_date
    or v_transaction.amount <> v_signed_amount
    or v_transaction.source_hash <> v_source_hash
  then
    raise exception 'banking_transaction_fact_mismatch';
  end if;

  update banking.transactions
  set matched_accounting_entry_id = p_accounting_entry_id,
      matched_action_reference = v_action_reference
  where id = v_transaction_id;

  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_company_id, v_actor_id, 'bank', 'bank_transaction_claimed',
    'Bank transaction claimed by external action ' || v_action_reference || '.'
  );

  return pg_catalog.jsonb_build_object(
    'transactionId', v_transaction_id,
    'accountingEntryId', p_accounting_entry_id,
    'actionReference', v_action_reference
  );
end;
$function$;

alter function banking.claim_transaction_for_external_action_v1(
  jsonb, uuid, text
) owner to banking_store_owner;

reset role;

revoke all on function banking.claim_transaction_for_external_action_v1(
  jsonb, uuid, text
) from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, talli_banking_backend;
grant usage on schema banking to investments_workflow_executor;
grant execute on function banking.claim_transaction_for_external_action_v1(
  jsonb, uuid, text
) to investments_workflow_executor;

revoke create on schema banking from banking_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke banking_store_owner, investments_workflow_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
