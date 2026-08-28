-- EXPAND/MIGRATE: account-free banking commands and the atomic ledger seam.

begin;

do $banking_workflow_migration_authority$
begin
  execute pg_catalog.format(
    'grant banking_store_owner, banking_workflow_store_owner to %I', current_user
  );
  execute pg_catalog.format(
    'grant create on schema banking, backend_system to %I', current_user
  );
end
$banking_workflow_migration_authority$;
grant usage, create on schema banking, backend_system to banking_store_owner;

create table if not exists backend_system.banking_command_receipts (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  api_major text not null check (api_major = 'v1'),
  actor_id uuid not null,
  company_id uuid not null references public.companies(id) on delete restrict,
  operation_name text not null check (operation_name = 'import_statement'),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  result jsonb not null,
  completed_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (api_major, actor_id, company_id, operation_name, idempotency_key)
);

alter table backend_system.banking_command_receipts enable row level security;
alter table backend_system.banking_command_receipts force row level security;
drop policy if exists "banking store reads command receipts"
  on backend_system.banking_command_receipts;
create policy "banking store reads command receipts"
on backend_system.banking_command_receipts for select to banking_store_owner
using (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "banking store appends command receipts"
  on backend_system.banking_command_receipts;
create policy "banking store appends command receipts"
on backend_system.banking_command_receipts for insert to banking_store_owner
with check (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function banking.import_statement_v1(
  p_request jsonb,
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
  v_idempotency_key text;
  v_fingerprint text;
  v_receipt backend_system.banking_command_receipts%rowtype;
  v_row jsonb;
  v_imported integer := 0;
  v_duplicates integer := 0;
  v_affected integer;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'banking_forbidden';
  end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_idempotency_key := p_request ->> 'idempotencyKey';
  exception when others then
    raise exception 'banking_invalid_input';
  end;
  if v_income_year not between 2000 and 2100
    or coalesce(v_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.jsonb_typeof(p_request -> 'transactions') is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_request -> 'transactions') not between 1 and 10000
  then
    raise exception 'banking_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(v_company_id) then
    raise exception 'banking_transaction_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'banking_forbidden';
  end if;
  if coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then
    raise exception 'banking_company_year_not_admitted';
  end if;

  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'banking-command:v1:' || v_actor_id::text || ':' || v_company_id::text
      || ':import_statement:' || v_idempotency_key,
    0
  )) then
    raise exception 'banking_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.banking_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = v_company_id
    and receipt.operation_name = 'import_statement'
    and receipt.idempotency_key = v_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'banking_idempotency_key_reused';
    end if;
    return v_receipt.result || pg_catalog.jsonb_build_object('replayed', true);
  end if;

  for v_row in
    select value from pg_catalog.jsonb_array_elements(p_request -> 'transactions')
  loop
    if pg_catalog.jsonb_typeof(v_row) is distinct from 'object'
      or coalesce(v_row ->> 'transactionDate', '') !~ '^\d{4}-\d{2}-\d{2}$'
      or extract(year from (v_row ->> 'transactionDate')::date) <> v_income_year
      or pg_catalog.btrim(coalesce(v_row ->> 'text', '')) = ''
      or pg_catalog.char_length(v_row ->> 'text') > 500
      or coalesce(v_row ->> 'amount', '') !~ '^-?[0-9]+([.][0-9]{1,2})?$'
      or (
        v_row ->> 'balance' is not null
        and (v_row ->> 'balance') !~ '^-?[0-9]+([.][0-9]{1,2})?$'
      )
      or coalesce(v_row ->> 'sourceHash', '') !~ '^[0-9a-f]{64}$'
    then
      raise exception 'banking_statement_invalid';
    end if;
    insert into banking.transactions (
      id, company_id, income_year, transaction_date, text, amount, balance,
      source_hash, created_by
    ) values (
      pg_catalog.gen_random_uuid(),
      v_company_id,
      v_income_year,
      (v_row ->> 'transactionDate')::date,
      pg_catalog.btrim(v_row ->> 'text'),
      (v_row ->> 'amount')::numeric,
      (v_row ->> 'balance')::numeric,
      v_row ->> 'sourceHash',
      v_actor_id
    )
    on conflict (company_id, income_year, source_hash) do nothing;
    get diagnostics v_affected = row_count;
    if v_affected = 1 then
      v_imported := v_imported + 1;
    else
      v_duplicates := v_duplicates + 1;
    end if;
  end loop;

  v_result := pg_catalog.jsonb_build_object(
    'importedCount', v_imported,
    'duplicateCount', v_duplicates,
    'transactions', pg_catalog.jsonb_build_array(),
    'replayed', false
  );
  insert into backend_system.banking_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, v_company_id, 'import_statement', v_idempotency_key,
    v_fingerprint, v_result
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'bank', 'bank_csv_imported',
    'Bank CSV imported (' || v_imported::text || ' new, '
      || v_duplicates::text || ' duplicates).'
  );
  return v_result;
exception
  when invalid_datetime_format or datetime_field_overflow or numeric_value_out_of_range then
    raise exception 'banking_statement_invalid';
end;
$function$;

create or replace function banking.suggestion_acceptance_replay_v1(
  p_request jsonb,
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
  v_transaction_id uuid;
  v_acceptance banking.suggestion_acceptances%rowtype;
  v_transaction banking.transactions%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_transaction_id := (p_request ->> 'bankTransactionId')::uuid;
  exception when others then raise exception 'banking_invalid_input'; end;
  if not public.company_access_is_accepted_member_v1(v_company_id) then
    raise exception 'banking_transaction_not_found';
  end if;
  select bank_row.* into v_transaction from banking.transactions bank_row
  where bank_row.id = v_transaction_id and bank_row.company_id = v_company_id;
  if not found then raise exception 'banking_transaction_not_found'; end if;
  select acceptance.* into v_acceptance
  from banking.suggestion_acceptances acceptance
  where acceptance.bank_transaction_id = v_transaction_id;
  if not found then return null; end if;
  if v_acceptance.suggestion_kind <> p_request ->> 'expectedSuggestion'
    or v_acceptance.rule_version <> p_request ->> 'expectedRuleVersion'
    or v_transaction.matched_accounting_entry_id <> v_acceptance.accounting_entry_id
  then raise exception 'banking_suggestion_acceptance_conflict'; end if;
  return pg_catalog.jsonb_build_object(
    'acceptanceId', v_acceptance.id,
    'bankTransactionId', v_acceptance.bank_transaction_id,
    'accountingEntryId', v_acceptance.accounting_entry_id,
    'suggestionKind', v_acceptance.suggestion_kind,
    'ruleVersion', v_acceptance.rule_version,
    'reason', v_acceptance.reason,
    'acceptedBy', v_acceptance.accepted_by,
    'acceptedAt', v_acceptance.accepted_at,
    'replayed', true
  );
end;
$function$;

create or replace function banking.prepare_suggestion_acceptance_v1(
  p_request jsonb,
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
  v_transaction banking.transactions%rowtype;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_transaction_id := (p_request ->> 'bankTransactionId')::uuid;
  exception when others then raise exception 'banking_invalid_input'; end;
  if not public.company_access_is_accepted_member_v1(v_company_id) then
    raise exception 'banking_transaction_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'banking_forbidden';
  end if;
  perform ledger.lock_company_year_v1(v_company_id, v_income_year);
  if coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_company_year_allows_consequential_v1(
      v_company_id, v_income_year
    )
  then raise exception 'banking_company_year_not_admitted'; end if;
  select bank_row.* into v_transaction from banking.transactions bank_row
  where bank_row.id = v_transaction_id
    and bank_row.company_id = v_company_id
    and bank_row.income_year = v_income_year
  for update;
  if not found then raise exception 'banking_transaction_not_found'; end if;
  if v_transaction.matched_accounting_entry_id is not null
    or v_transaction.matched_action_reference is not null
    or v_transaction.warning_accepted
  then raise exception 'banking_transaction_already_reconciled'; end if;
  return pg_catalog.jsonb_build_object(
    'transactionId', v_transaction.id,
    'companyId', v_transaction.company_id,
    'incomeYear', v_transaction.income_year,
    'transactionDate', v_transaction.transaction_date,
    'text', v_transaction.text,
    'amount', v_transaction.amount,
    'balance', v_transaction.balance,
    'sourceHash', v_transaction.source_hash,
    'matchedEntryId', v_transaction.matched_accounting_entry_id,
    'matchedActionReference', v_transaction.matched_action_reference,
    'warningAccepted', v_transaction.warning_accepted,
    'createdBy', v_transaction.created_by,
    'createdAt', v_transaction.created_at
  );
end;
$function$;

create or replace function banking.complete_suggestion_acceptance_v1(
  p_request jsonb,
  p_accounting_entry_id uuid,
  p_reason text,
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
  v_acceptance_id uuid;
  v_affected integer;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'banking_forbidden'; end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_transaction_id := (p_request ->> 'bankTransactionId')::uuid;
    v_acceptance_id := (p_request ->> 'acceptanceId')::uuid;
  exception when others then raise exception 'banking_invalid_input'; end;
  if p_accounting_entry_id is null
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or p_request ->> 'expectedSuggestion' not in (
      'BANK_FEE', 'SYSTEM_SUBSCRIPTION', 'DEPOSIT_INTEREST'
    )
  then raise exception 'banking_invalid_input'; end if;
  insert into banking.suggestion_acceptances (
    id, company_id, bank_transaction_id, accounting_entry_id,
    suggestion_kind, rule_version, reason, accepted_by
  ) values (
    v_acceptance_id, v_company_id, v_transaction_id, p_accounting_entry_id,
    p_request ->> 'expectedSuggestion', p_request ->> 'expectedRuleVersion',
    pg_catalog.btrim(p_reason), v_actor_id
  );
  update banking.transactions
  set matched_accounting_entry_id = p_accounting_entry_id
  where id = v_transaction_id
    and company_id = v_company_id
    and income_year = v_income_year
    and matched_accounting_entry_id is null
    and matched_action_reference is null
    and not warning_accepted;
  get diagnostics v_affected = row_count;
  if v_affected <> 1 then
    raise exception 'banking_transaction_already_reconciled';
  end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'bank', 'bank_suggestion_accepted',
    'Owner accepted banking suggestion '
      || (p_request ->> 'expectedSuggestion') || ' version '
      || (p_request ->> 'expectedRuleVersion') || '.'
  );
  return pg_catalog.jsonb_build_object(
    'acceptanceId', v_acceptance_id,
    'bankTransactionId', v_transaction_id,
    'accountingEntryId', p_accounting_entry_id,
    'suggestionKind', p_request ->> 'expectedSuggestion',
    'ruleVersion', p_request ->> 'expectedRuleVersion',
    'reason', pg_catalog.btrim(p_reason),
    'acceptedBy', v_actor_id,
    'acceptedAt', pg_catalog.statement_timestamp(),
    'replayed', false
  );
end;
$function$;

create or replace function backend_system.prevent_banking_command_receipt_mutation()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  raise exception 'banking_command_receipt_is_immutable';
end;
$function$;

drop trigger if exists banking_command_receipts_immutable
  on backend_system.banking_command_receipts;
create trigger banking_command_receipts_immutable
before update or delete on backend_system.banking_command_receipts
for each row execute function
  backend_system.prevent_banking_command_receipt_mutation();

alter function banking.import_statement_v1(jsonb, text)
  owner to banking_store_owner;
alter function banking.suggestion_acceptance_replay_v1(jsonb, text)
  owner to banking_store_owner;
alter function banking.prepare_suggestion_acceptance_v1(jsonb, text)
  owner to banking_store_owner;
alter function banking.complete_suggestion_acceptance_v1(jsonb, uuid, text, text)
  owner to banking_store_owner;
alter function backend_system.prevent_banking_command_receipt_mutation()
  owner to banking_store_owner;
alter table backend_system.banking_command_receipts owner to banking_store_owner;

grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_is_accepted_member_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_company_year_allows_consequential_v1(uuid, integer),
  ledger.lock_company_year_v1(uuid, integer)
to banking_store_owner;

revoke all on function
  banking.import_statement_v1(jsonb, text),
  banking.suggestion_acceptance_replay_v1(jsonb, text),
  banking.prepare_suggestion_acceptance_v1(jsonb, text),
  banking.complete_suggestion_acceptance_v1(jsonb, uuid, text, text)
from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, talli_banking_backend;
grant execute on function banking.import_statement_v1(jsonb, text)
  to banking_executor;
grant execute on function
  banking.suggestion_acceptance_replay_v1(jsonb, text),
  banking.prepare_suggestion_acceptance_v1(jsonb, text),
  banking.complete_suggestion_acceptance_v1(jsonb, uuid, text, text),
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  )
to banking_workflow_executor;
grant usage on schema ledger to banking_workflow_executor;

revoke all on backend_system.banking_command_receipts
from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, talli_banking_backend;
grant select, insert on backend_system.banking_command_receipts
to banking_store_owner;

revoke create on schema banking, backend_system from banking_store_owner;
do $banking_workflow_revoke_migration_authority$
begin
  execute pg_catalog.format(
    'revoke create on schema banking, backend_system from %I', current_user
  );
  execute pg_catalog.format(
    'revoke banking_store_owner, banking_workflow_store_owner from %I',
    current_user
  );
end
$banking_workflow_revoke_migration_authority$;

commit;
