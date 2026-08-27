-- EXPAND/MIGRATE: request-bound coordinators for the nine remaining ledger writers.
-- Business posting policy stays in Python; these routines own only locked compatibility
-- facts, future-capability state, immutable receipts, and the five characterized audits.

begin;

-- The expand migration leaves both storage-owner roles non-inheritable and
-- ungranted. Hosted Supabase migrations therefore need narrowly temporary
-- membership to alter the owned receipt table and create coordinator routines
-- in the locked schemas. The membership is revoked before commit.
do $ledger_writer_migration_membership$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner, ledger_workflow_store_owner to %I', current_user
  );
  execute pg_catalog.format(
    'grant create on schema ledger, backend_system to %I', current_user
  );
end
$ledger_writer_migration_membership$;

alter table backend_system.ledger_workflow_receipts
  drop constraint if exists ledger_workflow_receipts_operation_name_check;
alter table backend_system.ledger_workflow_receipts
  add constraint ledger_workflow_receipts_operation_name_check check (
    operation_name in (
      'new_year_start',
      'record_administrative_cost',
      'record_investment_dividend',
      'record_shareholder_loan',
      'record_tax_settlement',
      'accept_bank_transaction_suggestion',
      'record_investment_purchase_fifo',
      'record_investment_sale_fifo',
      'finalize_corporate_decision',
      'record_owner_dividend_payment'
    )
  );

create or replace function backend_system.claim_ledger_writer_v1(
  p_operation_name text,
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
  v_idempotency_key text;
  v_fingerprint text;
  v_receipt backend_system.ledger_workflow_receipts%rowtype;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
    or p_operation_name not in (
      'record_administrative_cost', 'record_investment_dividend',
      'record_shareholder_loan', 'record_tax_settlement',
      'accept_bank_transaction_suggestion', 'record_investment_purchase_fifo',
      'record_investment_sale_fifo', 'finalize_corporate_decision',
      'record_owner_dividend_payment'
    )
  then
    raise exception 'ledger_forbidden';
  end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
  exception when others then
    raise exception 'ledger_invalid_input';
  end;
  v_idempotency_key := p_request ->> 'idempotencyKey';
  if v_company_id is null
    or coalesce(v_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or coalesce(p_request ->> 'correlationId', '') = ''
    or coalesce((p_request ->> 'incomeYear')::integer, 0) not between 2000 and 2100
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(v_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger-writer:v1:' || v_actor_id::text || ':' || v_company_id::text
      || ':' || p_operation_name || ':' || v_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.ledger_workflow_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = v_company_id
    and receipt.operation_name = p_operation_name
    and receipt.idempotency_key = v_idempotency_key;
  if not found then
    return null;
  end if;
  if v_receipt.request_fingerprint <> v_fingerprint then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  return v_receipt.result;
end;
$function$;

create or replace function backend_system.lock_ledger_writer_year_v1(p_request jsonb)
returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
begin
  perform ledger.lock_company_year_v1(v_company_id, v_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    v_company_id, v_income_year
  ) then raise exception 'ledger_company_year_not_admitted'; end if;
  if exists (
    select 1 from ledger.period_locks period_lock
    where period_lock.company_id = v_company_id
      and period_lock.income_year = v_income_year
  ) then raise exception 'ledger_period_locked'; end if;
end;
$function$;

create or replace function backend_system.prepare_administrative_cost_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_amount numeric := (p_request ->> 'amount')::numeric;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_administrative_cost', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  if v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or pg_catalog.btrim(coalesce(p_request ->> 'payee', '')) = ''
    or (p_request ->> 'paidDate')::date is null
    or extract(year from (p_request ->> 'paidDate')::date)::integer <> v_income_year
    or p_request ->> 'category' not in (
      'BANK_FEE', 'ACCOUNTING_FEE', 'SOFTWARE', 'PUBLIC_FEE',
      'LEGAL_ADVISORY', 'OTHER_ADMIN_COST'
    )
  then raise exception 'ledger_invalid_input'; end if;
  select bank.* into v_bank from public.bank_transactions bank
  where bank.id = v_bank_id for update;
  if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank.matched_entry_id is not null then
    if v_bank.matched_action_id is null and not v_bank.accepted_warning
      and exists (
        select 1 from ledger.entries entry where entry.id = v_bank.matched_entry_id
          and entry.company_id = v_company_id
          and entry.entry_kind = 'ADMINISTRATIVE_COST'
      )
    then
      return pg_catalog.jsonb_build_object(
        'replay', backend_system.ledger_writer_entry_result_v1(
          v_bank.matched_entry_id,
          pg_catalog.jsonb_build_object('auditRequired', true)
        )
      );
    end if;
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if v_bank.matched_action_id is not null or v_bank.accepted_warning
    or v_bank.amount <> -v_amount
  then raise exception 'ledger_invalid_input'; end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document
    where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id
      or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object('replay', null);
end;
$function$;

create or replace function backend_system.complete_administrative_cost_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not exists (
      select 1 from ledger.entries entry
      where entry.id = p_entry_id
        and entry.company_id = (p_request ->> 'companyId')::uuid
        and entry.income_year = (p_request ->> 'incomeYear')::integer
        and entry.entry_kind = 'ADMINISTRATIVE_COST'
        and entry.source_capability = 'BANKING'
        and entry.source_record_id = p_request ->> 'bankTransactionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  update public.bank_transactions set matched_entry_id = p_entry_id
  where id = v_bank_id and matched_entry_id is null
    and matched_action_id is null and not accepted_warning;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'auditRequired', true,
      'auditAction', 'admin_cost_posted_and_matched'
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_administrative_cost', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_investment_dividend_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_existing public.holding_actions%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_amount numeric := (p_request ->> 'grossAmount')::numeric;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_investment_dividend', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select action.* into v_existing from public.holding_actions action
  where action.id = v_action_id;
  if found then
    if v_existing.company_id <> v_company_id
      or v_existing.action_type <> 'dividend_received'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'actionId', v_existing.id, 'auditRequired', true,
          'auditAction', 'dividend_received_recorded'
        )
      )
    );
  end if;
  if pg_catalog.btrim(coalesce(p_request ->> 'payingCompanyName', '')) = ''
    or pg_catalog.btrim(coalesce(p_request ->> 'linkedInvestmentId', '')) = ''
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or extract(year from (p_request ->> 'paidDate')::date)::integer <> v_income_year
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank_id is not null then
    select bank.* into v_bank from public.bank_transactions bank
    where bank.id = v_bank_id for update;
    if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
      or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
      or v_bank.accepted_warning or v_bank.amount <> v_amount
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object('replay', null);
end;
$function$;

create or replace function backend_system.complete_investment_dividend_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_amount numeric := (p_request ->> 'grossAmount')::numeric;
  v_payload jsonb;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'DIVIDEND_RECEIVED'
        and entry.source_record_id = p_request ->> 'actionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  v_payload := pg_catalog.jsonb_build_object(
    'paying_company_name', pg_catalog.btrim(p_request ->> 'payingCompanyName'),
    'declared_date', (p_request ->> 'declaredDate')::date,
    'paid_date', (p_request ->> 'paidDate')::date,
    'gross_amount', v_amount,
    'linked_investment_id', p_request ->> 'linkedInvestmentId',
    'tax_treatment', 'fritaksmetoden',
    'taxable_add_back', pg_catalog.round(v_amount * 0.03, 2),
    'bank_transaction_id', nullif(p_request ->> 'bankTransactionId', ''),
    'document_id', nullif(p_request ->> 'documentId', ''),
    'document_status', p_request ->> 'documentStatus'
  );
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'dividend_received',
    (p_request ->> 'paidDate')::date, v_payload, p_entry_id, v_bank_id,
    nullif(p_request ->> 'documentId', '')::uuid, 'ready', v_actor_id
  );
  if v_bank_id is not null then
    update public.bank_transactions set matched_action_id = v_action_id::text
    where id = v_bank_id and matched_entry_id is null and matched_action_id is null
      and not accepted_warning;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  end if;
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'actionId', v_action_id, 'auditRequired', true,
      'auditAction', 'dividend_received_recorded'
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_investment_dividend', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_shareholder_loan_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_existing public.holding_actions%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_amount numeric := (p_request ->> 'amount')::numeric;
  v_expected_bank numeric;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_shareholder_loan', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select action.* into v_existing from public.holding_actions action where action.id = v_action_id;
  if found then
    if v_existing.company_id <> v_company_id or v_existing.action_type <> 'shareholder_loan'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'actionId', v_existing.id, 'auditRequired', true,
          'auditAction', 'shareholder_loan_recorded'
        )
      )
    );
  end if;
  if v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or pg_catalog.btrim(coalesce(p_request ->> 'counterpartyName', '')) = ''
    or p_request ->> 'direction' not in (
      'shareholder_to_company', 'company_to_corporate_shareholder'
    )
    or coalesce((p_request ->> 'relatedPartySecurity')::boolean, false)
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or extract(year from (p_request ->> 'loanDate')::date)::integer <> v_income_year
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank_id is not null then
    v_expected_bank := case when p_request ->> 'direction' = 'shareholder_to_company'
      then v_amount else -v_amount end;
    select bank.* into v_bank from public.bank_transactions bank
    where bank.id = v_bank_id for update;
    if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
      or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
      or v_bank.accepted_warning or v_bank.amount <> v_expected_bank
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object('replay', null);
end;
$function$;

create or replace function backend_system.complete_shareholder_loan_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_payload jsonb;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'SHAREHOLDER_LOAN'
        and entry.source_record_id = p_request ->> 'actionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  v_payload := pg_catalog.jsonb_build_object(
    'loan_date', (p_request ->> 'loanDate')::date,
    'amount', (p_request ->> 'amount')::numeric,
    'direction', p_request ->> 'direction',
    'counterparty_name', pg_catalog.btrim(p_request ->> 'counterpartyName'),
    'document_status', p_request ->> 'documentStatus',
    'interest_modelled', coalesce((p_request ->> 'interestModelled')::boolean, false),
    'related_party_security', false,
    'bank_transaction_id', nullif(p_request ->> 'bankTransactionId', ''),
    'document_id', nullif(p_request ->> 'documentId', '')
  );
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'shareholder_loan',
    (p_request ->> 'loanDate')::date, v_payload, p_entry_id, v_bank_id,
    nullif(p_request ->> 'documentId', '')::uuid, 'ready', v_actor_id
  );
  if v_bank_id is not null then
    update public.bank_transactions set matched_action_id = v_action_id::text
    where id = v_bank_id and matched_entry_id is null and matched_action_id is null
      and not accepted_warning;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  end if;
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'actionId', v_action_id, 'auditRequired', true,
      'auditAction', 'shareholder_loan_recorded'
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_shareholder_loan', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_tax_settlement_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_existing public.holding_actions%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_amount numeric := (p_request ->> 'amount')::numeric;
  v_kind text := p_request ->> 'settlementKind';
  v_expected_bank numeric;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_tax_settlement', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select action.* into v_existing from public.holding_actions action where action.id = v_action_id;
  if found then
    if v_existing.company_id <> v_company_id or v_existing.action_type <> 'tax_settlement'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'actionId', v_existing.id, 'auditRequired', true,
          'auditAction', 'tax_settlement_recorded'
        )
      )
    );
  end if;
  if v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or v_kind not in ('payable', 'payment', 'refund')
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or extract(year from (p_request ->> 'settlementDate')::date)::integer <> v_income_year
    or (v_kind = 'payable' and v_bank_id is not null)
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank_id is not null then
    v_expected_bank := case when v_kind = 'payment' then -v_amount else v_amount end;
    select bank.* into v_bank from public.bank_transactions bank
    where bank.id = v_bank_id for update;
    if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
      or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
      or v_bank.accepted_warning or v_bank.amount <> v_expected_bank
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object('replay', null);
end;
$function$;

create or replace function backend_system.complete_tax_settlement_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_payload jsonb;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'TAX_SETTLEMENT'
        and entry.source_record_id = p_request ->> 'actionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  v_payload := pg_catalog.jsonb_build_object(
    'settlement_date', (p_request ->> 'settlementDate')::date,
    'amount', (p_request ->> 'amount')::numeric,
    'settlement_type', p_request ->> 'settlementKind',
    'document_status', p_request ->> 'documentStatus',
    'bank_transaction_id', nullif(p_request ->> 'bankTransactionId', ''),
    'document_id', nullif(p_request ->> 'documentId', '')
  );
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'tax_settlement',
    (p_request ->> 'settlementDate')::date, v_payload, p_entry_id, v_bank_id,
    nullif(p_request ->> 'documentId', '')::uuid, 'ready', v_actor_id
  );
  if v_bank_id is not null then
    update public.bank_transactions set matched_action_id = v_action_id::text
    where id = v_bank_id and matched_entry_id is null and matched_action_id is null
      and not accepted_warning;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  end if;
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'actionId', v_action_id, 'auditRequired', true,
      'auditAction', 'tax_settlement_recorded'
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_tax_settlement', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.complete_ledger_writer_v1(
  p_operation_name text,
  p_request jsonb,
  p_result jsonb,
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
  v_idempotency_key text;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
    or pg_catalog.jsonb_typeof(p_result) is distinct from 'object'
  then
    raise exception 'ledger_forbidden';
  end if;
  v_company_id := (p_request ->> 'companyId')::uuid;
  v_idempotency_key := p_request ->> 'idempotencyKey';
  insert into backend_system.ledger_workflow_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, v_company_id, p_operation_name, v_idempotency_key,
    pg_catalog.encode(extensions.digest(p_request::text, 'sha256'), 'hex'), p_result
  );
  return p_result;
end;
$function$;

create or replace function backend_system.ledger_writer_entry_result_v1(
  p_entry_id uuid,
  p_extra jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_entry ledger.entries%rowtype;
begin
  select entry.* into v_entry from ledger.entries entry where entry.id = p_entry_id;
  if not found or pg_catalog.jsonb_typeof(p_extra) is distinct from 'object' then
    raise exception 'ledger_dependency_unavailable';
  end if;
  return pg_catalog.jsonb_build_object(
    'entryId', v_entry.id,
    'companyId', v_entry.company_id,
    'incomeYear', v_entry.income_year,
    'entryKind', v_entry.entry_kind,
    'postedAt', v_entry.posted_at
  ) || p_extra;
end;
$function$;

create or replace function ledger.post_entry_with_id_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
  p_risk_flags jsonb,
  p_warning_accepted boolean,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text,
  p_requested_entry_id uuid
)
returns table (
  ledger_entry_id uuid,
  company_id uuid,
  income_year integer,
  entry_kind text,
  posted_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_posted_at timestamptz;
  v_computed_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_requested_entry_id is null
    or p_company_id is null or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_memo, '')) = ''
    or pg_catalog.btrim(coalesce(p_source_record_id, '')) = ''
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
    or p_source_capability not in (
      'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
      'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING'
    )
    or pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
      'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
      'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT'
    )
    or pg_catalog.jsonb_typeof(p_risk_flags) is distinct from 'array'
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  v_computed_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id, 'incomeYear', p_income_year,
      'entryKind', pg_catalog.upper(p_entry_kind), 'memo', pg_catalog.btrim(p_memo),
      'lines', ledger.normalize_lines_v1(p_lines), 'riskFlags', p_risk_flags,
      'warningAccepted', p_warning_accepted, 'sourceCapability', p_source_capability,
      'sourceRecordId', pg_catalog.btrim(p_source_record_id),
      'requestedEntryId', p_requested_entry_id
    )::text, 'sha256'
  ), 'hex');
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':post_entry:' || p_idempotency_key, 0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1' and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id and receipt.operation_name = 'post_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint
      or (v_receipt.result ->> 'ledger_entry_id')::uuid <> p_requested_entry_id
    then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'ledger_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      v_receipt.result ->> 'entry_kind',
      (v_receipt.result ->> 'posted_at')::timestamptz, true;
    return;
  end if;
  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;
  if exists (
    select 1 from ledger.period_locks period_lock
    where period_lock.company_id = p_company_id
      and period_lock.income_year = p_income_year
  ) then
    raise exception 'ledger_period_locked';
  end if;
  if exists (
    select 1 from ledger.entries entry
    where entry.id = p_requested_entry_id
      or (
        entry.company_id = p_company_id
        and entry.source_capability = p_source_capability
        and entry.source_record_id = p_source_record_id
      )
  ) then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  v_posted_at := pg_catalog.statement_timestamp();
  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    p_requested_entry_id, p_company_id, p_income_year,
    pg_catalog.upper(p_entry_kind), pg_catalog.btrim(p_memo),
    ledger.normalize_lines_v1(p_lines), p_risk_flags,
    case when p_warning_accepted then v_actor_id else null end,
    case when p_warning_accepted then v_posted_at else null end,
    v_posted_at, v_actor_id, v_posted_at, p_source_capability,
    pg_catalog.btrim(p_source_record_id), pg_catalog.btrim(p_correlation_id)
  );
  v_result := pg_catalog.jsonb_build_object(
    'ledger_entry_id', p_requested_entry_id, 'company_id', p_company_id,
    'income_year', p_income_year, 'entry_kind', pg_catalog.upper(p_entry_kind),
    'posted_at', v_posted_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'post_entry', p_idempotency_key,
    v_computed_fingerprint, v_result
  );
  return query select p_requested_entry_id, p_company_id, p_income_year,
    pg_catalog.upper(p_entry_kind), v_posted_at, false;
end;
$function$;

create or replace function backend_system.prepare_bank_transaction_suggestion_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_bank public.bank_transactions%rowtype;
  v_existing public.bank_suggestion_acceptances%rowtype;
  v_bank_match boolean;
  v_subscription_match boolean;
  v_interest_match boolean;
  v_match_count integer;
  v_rule text := p_request ->> 'rule';
  v_version text := p_request ->> 'ruleVersion';
  v_text text;
  v_amount numeric;
  v_reason text;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'accept_bank_transaction_suggestion', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select bank.* into v_bank from public.bank_transactions bank
  where bank.id = (p_request ->> 'bankTransactionId')::uuid for update;
  if not found or v_bank.company_id <> (p_request ->> 'companyId')::uuid
    or v_bank.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'ledger_invalid_input'; end if;
  select acceptance.* into v_existing from public.bank_suggestion_acceptances acceptance
  where acceptance.bank_transaction_id = v_bank.id;
  if found then
    if v_existing.rule_id = v_rule and v_existing.rule_version = v_version
      and v_bank.matched_entry_id = v_existing.ledger_entry_id
    then
      return pg_catalog.jsonb_build_object(
        'replay', backend_system.ledger_writer_entry_result_v1(
          v_existing.ledger_entry_id,
          pg_catalog.jsonb_build_object(
            'acceptanceId', v_existing.id, 'rule', v_rule,
            'ruleVersion', v_version, 'auditRequired', false
          )
        )
      );
    end if;
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
    or v_bank.accepted_warning or v_version <> '2026-07-13.1'
  then raise exception 'ledger_invalid_input'; end if;
  v_text := pg_catalog.lower(pg_catalog.btrim(coalesce(v_bank.text, '')));
  v_bank_match := v_text ~ '(^|[^[:alnum:]])(årsgebyr|arsgebyr|bankgebyr|bank fee|annual fee)($|[^[:alnum:]])';
  v_subscription_match := v_text ~ '(^|[^[:alnum:]])(systemabonnement|system subscription)($|[^[:alnum:]])';
  v_interest_match := v_text ~ '(^|[^[:alnum:]])(renter|rente|interest)($|[^[:alnum:]])';
  v_match_count := v_bank_match::integer + v_subscription_match::integer + v_interest_match::integer;
  if v_match_count <> 1
    or (v_rule = 'bank_fee' and not v_bank_match)
    or (v_rule = 'system_subscription' and not v_subscription_match)
    or (v_rule = 'deposit_interest' and not v_interest_match)
    or v_rule not in ('bank_fee', 'system_subscription', 'deposit_interest')
    or (v_rule in ('bank_fee', 'system_subscription') and v_bank.amount >= 0)
    or (v_rule = 'deposit_interest' and v_bank.amount <= 0)
  then raise exception 'ledger_invalid_input'; end if;
  v_amount := pg_catalog.round(pg_catalog.abs(v_bank.amount), 2);
  if v_amount <= 0 then raise exception 'ledger_invalid_input'; end if;
  v_reason := case v_rule
    when 'bank_fee' then 'Teksten beskriver et bankgebyr og beløpet er en utbetaling.'
    when 'system_subscription' then 'Teksten beskriver et systemabonnement og beløpet er en utbetaling.'
    else 'Teksten beskriver renteinntekt og beløpet er en innbetaling.' end;
  return pg_catalog.jsonb_build_object(
    'replay', null, 'amount', v_amount, 'transactionText', v_bank.text,
    'reason', v_reason
  );
end;
$function$;

create or replace function backend_system.complete_bank_transaction_suggestion_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_acceptance_id uuid := (p_request ->> 'acceptanceId')::uuid;
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_entry ledger.entries%rowtype;
  v_result jsonb;
  v_count integer;
begin
  select entry.* into v_entry from ledger.entries entry where entry.id = p_entry_id;
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not found or v_entry.company_id <> (p_request ->> 'companyId')::uuid
    or v_entry.entry_kind <> 'BANK_RULE_SUGGESTION'
    or v_entry.source_record_id <> v_acceptance_id::text
  then raise exception 'ledger_dependency_unavailable'; end if;
  insert into public.bank_suggestion_acceptances (
    id, company_id, bank_transaction_id, ledger_entry_id, rule_id,
    rule_version, reason, lines, accepted_by
  ) values (
    v_acceptance_id, v_entry.company_id, v_bank_id, p_entry_id,
    p_request ->> 'rule', p_request ->> 'ruleVersion',
    p_prepared ->> 'reason', v_entry.lines, v_actor_id
  );
  update public.bank_transactions set matched_entry_id = p_entry_id
  where id = v_bank_id and matched_entry_id is null and matched_action_id is null
    and not accepted_warning;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_entry.company_id, v_actor_id, 'bank', 'bank_suggestion_accepted',
    'Eier godkjente bankregel ' || (p_request ->> 'rule') || ' versjon '
      || (p_request ->> 'ruleVersion') || '.'
  );
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'acceptanceId', v_acceptance_id, 'rule', p_request ->> 'rule',
      'ruleVersion', p_request ->> 'ruleVersion', 'auditRequired', false
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'accept_bank_transaction_suggestion', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_investment_purchase_fifo_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_existing public.holding_actions%rowtype;
  v_position public.investment_positions%rowtype;
  v_position_id uuid;
  v_position_created boolean := false;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_amount numeric := (p_request ->> 'purchaseAmount')::numeric;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_investment_purchase_fifo', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select action.* into v_existing from public.holding_actions action where action.id = v_action_id;
  if found then
    if v_existing.company_id <> v_company_id or v_existing.action_type <> 'share_purchase'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'actionId', v_existing.id,
          'positionId', v_existing.payload ->> 'position_id',
          'lotId', v_existing.payload ->> 'acquisition_lot_id',
          'auditRequired', false
        )
      )
    );
  end if;
  if pg_catalog.btrim(coalesce(p_request ->> 'investmentKey', '')) = ''
    or pg_catalog.btrim(coalesce(p_request ->> 'investmentName', '')) = ''
    or p_request ->> 'investmentKind' <> 'norwegian_private_company'
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or (p_request ->> 'shareCount')::bigint <= 0
    or v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or extract(year from (p_request ->> 'acquisitionDate')::date)::integer <> v_income_year
    or (
      nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), '') is not null
      and pg_catalog.btrim(p_request ->> 'orgNumber') !~ '^[0-9]{9}$'
    )
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank_id is not null then
    select bank.* into v_bank from public.bank_transactions bank
    where bank.id = v_bank_id for update;
    if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
      or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
      or v_bank.accepted_warning or v_bank.amount <> -v_amount
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  insert into public.investment_positions (
    company_id, investment_key, name, kind, tax_treatment, org_number,
    share_count, cost_basis, movements, lot_history_status, created_by
  ) values (
    v_company_id, pg_catalog.btrim(p_request ->> 'investmentKey'),
    pg_catalog.btrim(p_request ->> 'investmentName'),
    p_request ->> 'investmentKind', p_request ->> 'taxTreatment',
    nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''),
    0, 0, '[]'::jsonb, 'complete', public.company_access_auth_uid_v1()
  ) on conflict (company_id, investment_key) do nothing returning id into v_position_id;
  if v_position_id is null then
    select position.* into v_position from public.investment_positions position
    where position.company_id = v_company_id
      and position.investment_key = pg_catalog.btrim(p_request ->> 'investmentKey')
    for update;
    v_position_id := v_position.id;
    if v_position.kind <> p_request ->> 'investmentKind'
      or v_position.tax_treatment <> p_request ->> 'taxTreatment'
      or coalesce(v_position.org_number, '') <>
        coalesce(nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''), '')
    then raise exception 'ledger_invalid_input'; end if;
    if v_position.lot_history_status = 'needs_reconstruction'
      and v_position.share_count = 0 and v_position.cost_basis = 0
    then
      update public.investment_positions set lot_history_status = 'complete'
      where id = v_position_id;
    end if;
  else
    v_position_created := true;
  end if;
  return pg_catalog.jsonb_build_object(
    'replay', null, 'positionId', v_position_id,
    'lotId', pg_catalog.gen_random_uuid(), 'positionCreated', v_position_created
  );
end;
$function$;

create or replace function backend_system.complete_investment_purchase_fifo_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_position_id uuid := (p_prepared ->> 'positionId')::uuid;
  v_lot_id uuid := (p_prepared ->> 'lotId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_amount numeric := (p_request ->> 'purchaseAmount')::numeric;
  v_payload jsonb;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'SHARE_PURCHASE'
        and entry.source_record_id = p_request ->> 'actionId'
    )
    or not exists (
      select 1 from public.investment_positions position
      where position.id = v_position_id
        and position.company_id = (p_request ->> 'companyId')::uuid
        and position.investment_key = pg_catalog.btrim(p_request ->> 'investmentKey')
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  v_payload := pg_catalog.jsonb_build_object(
    'investment_key', pg_catalog.btrim(p_request ->> 'investmentKey'),
    'investment_name', pg_catalog.btrim(p_request ->> 'investmentName'),
    'investment_kind', p_request ->> 'investmentKind',
    'tax_treatment', p_request ->> 'taxTreatment',
    'acquisition_date', (p_request ->> 'acquisitionDate')::date,
    'share_count', (p_request ->> 'shareCount')::bigint,
    'purchase_amount', v_amount,
    'org_number', nullif(pg_catalog.btrim(coalesce(p_request ->> 'orgNumber', '')), ''),
    'bank_transaction_id', nullif(p_request ->> 'bankTransactionId', ''),
    'document_id', nullif(p_request ->> 'documentId', ''),
    'document_status', p_request ->> 'documentStatus',
    'acquisition_lot_id', v_lot_id,
    'position_id', v_position_id
  );
  perform pg_catalog.set_config('talli.investment_action_write', 'on', true);
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'share_purchase',
    (p_request ->> 'acquisitionDate')::date, v_payload, p_entry_id, v_bank_id,
    nullif(p_request ->> 'documentId', '')::uuid, 'ready', v_actor_id
  );
  insert into public.investment_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by
  ) values (
    v_lot_id, (p_request ->> 'companyId')::uuid, v_position_id, v_action_id,
    (p_request ->> 'acquisitionDate')::date,
    (p_request ->> 'shareCount')::bigint, (p_request ->> 'shareCount')::bigint,
    v_amount, v_amount, v_actor_id
  );
  update public.investment_positions
  set share_count = share_count + (p_request ->> 'shareCount')::bigint,
      cost_basis = cost_basis + v_amount,
      movements = movements || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'action_id', v_action_id, 'movement_type', 'purchase',
        'movement_date', (p_request ->> 'acquisitionDate')::date,
        'share_delta', (p_request ->> 'shareCount')::bigint,
        'cost_basis_delta', v_amount, 'amount', v_amount, 'lot_id', v_lot_id
      )), updated_at = pg_catalog.now()
  where id = v_position_id;
  if v_bank_id is not null then
    update public.bank_transactions set matched_action_id = v_action_id::text
    where id = v_bank_id and matched_action_id is null and matched_entry_id is null;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    (p_request ->> 'companyId')::uuid, v_actor_id, 'ledger',
    'share_purchase_recorded', 'Aksjekjøp postert for '
      || pg_catalog.btrim(p_request ->> 'investmentName') || ' i '
      || (p_request ->> 'incomeYear') || '.'
  );
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'actionId', v_action_id, 'positionId', v_position_id, 'lotId', v_lot_id,
      'positionCreated', (p_prepared ->> 'positionCreated')::boolean,
      'payload', v_payload, 'auditRequired', false
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_investment_purchase_fifo', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_investment_sale_fifo_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_existing public.holding_actions%rowtype;
  v_position public.investment_positions%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_lot public.investment_lots%rowtype;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_position_id uuid := (p_request ->> 'positionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_document_id uuid := nullif(p_request ->> 'documentId', '')::uuid;
  v_sold bigint := (p_request ->> 'soldShareCount')::bigint;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_available_shares bigint;
  v_available_cost numeric;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_cost numeric;
  v_cost numeric := 0;
  v_allocations jsonb := '[]'::jsonb;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_investment_sale_fifo', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select action.* into v_existing from public.holding_actions action where action.id = v_action_id;
  if found then
    if v_existing.company_id <> v_company_id or v_existing.action_type <> 'share_sale'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'actionId', v_existing.id, 'positionId', v_existing.payload ->> 'position_id',
          'payload', v_existing.payload, 'auditRequired', false
        )
      )
    );
  end if;
  if v_sold <= 0 or v_proceeds < 0 or pg_catalog.round(v_proceeds, 2) <> v_proceeds
    or extract(year from (p_request ->> 'saleDate')::date)::integer <> v_income_year
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
  then raise exception 'ledger_invalid_input'; end if;
  select position.* into v_position from public.investment_positions position
  where position.id = v_position_id for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.lot_history_status <> 'complete'
  then raise exception 'ledger_invalid_input'; end if;
  perform 1 from public.investment_lots lot
  where lot.position_id = v_position_id and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id for update;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0)
  into v_available_shares, v_available_cost
  from public.investment_lots lot
  where lot.position_id = v_position_id and lot.remaining_share_count > 0;
  if v_available_shares = 0 or v_available_shares::numeric <> v_position.share_count
    or v_available_cost <> v_position.cost_basis or v_sold > v_available_shares
  then raise exception 'ledger_invalid_input'; end if;
  if v_bank_id is not null then
    select bank.* into v_bank from public.bank_transactions bank
    where bank.id = v_bank_id for update;
    if not found or v_bank.company_id <> v_company_id or v_bank.income_year <> v_income_year
      or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
      or v_bank.accepted_warning or v_bank.amount <> v_proceeds
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  if v_document_id is not null then
    select document.* into v_document from public.documents document where document.id = v_document_id;
    if not found or v_document.company_id <> v_company_id or v_document.income_year <> v_income_year
    then raise exception 'ledger_invalid_input'; end if;
  end if;
  v_left := v_sold;
  for v_lot in
    select lot.* from public.investment_lots lot
    where lot.position_id = v_position_id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := pg_catalog.least(v_left, v_lot.remaining_share_count);
    v_allocated_cost := case when v_allocated_shares = v_lot.remaining_share_count
      then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares / v_lot.remaining_share_count, 2
      ) end;
    v_left := v_left - v_allocated_shares;
    v_cost := v_cost + v_allocated_cost;
    v_allocations := v_allocations || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'lot_id', v_lot.id, 'acquisition_date', v_lot.acquisition_date,
      'share_count', v_allocated_shares, 'cost_basis', v_allocated_cost,
      'expected_remaining_share_count', v_lot.remaining_share_count,
      'expected_remaining_cost_basis', v_lot.remaining_cost_basis
    ));
  end loop;
  if v_left <> 0 then raise exception 'ledger_dependency_unavailable'; end if;
  return pg_catalog.jsonb_build_object(
    'replay', null, 'investmentName', v_position.name,
    'investmentKey', v_position.investment_key,
    'taxTreatment', v_position.tax_treatment,
    'fifoCostBasisReduction', v_cost,
    'remainingShareCount', v_available_shares - v_sold,
    'remainingCostBasis', v_available_cost - v_cost,
    'allocations', v_allocations
  );
end;
$function$;

create or replace function backend_system.complete_investment_sale_fifo_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
  v_position_id uuid := (p_request ->> 'positionId')::uuid;
  v_bank_id uuid := nullif(p_request ->> 'bankTransactionId', '')::uuid;
  v_allocation jsonb;
  v_allocations jsonb := p_prepared -> 'allocations';
  v_cost numeric := (p_prepared ->> 'fifoCostBasisReduction')::numeric;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_payload jsonb;
  v_result jsonb;
  v_count integer;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(v_allocations) is distinct from 'array'
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'SHARE_SALE'
        and entry.source_record_id = p_request ->> 'actionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  for v_allocation in select value from pg_catalog.jsonb_array_elements(v_allocations)
  loop
    update public.investment_lots
    set remaining_share_count = remaining_share_count - (v_allocation ->> 'share_count')::bigint,
        remaining_cost_basis = remaining_cost_basis - (v_allocation ->> 'cost_basis')::numeric
    where id = (v_allocation ->> 'lot_id')::uuid
      and position_id = v_position_id
      and remaining_share_count = (v_allocation ->> 'expected_remaining_share_count')::bigint
      and remaining_cost_basis = (v_allocation ->> 'expected_remaining_cost_basis')::numeric;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_dependency_unavailable'; end if;
  end loop;
  v_payload := pg_catalog.jsonb_build_object(
    'position_id', v_position_id,
    'investment_key', p_prepared ->> 'investmentKey',
    'investment_name', p_prepared ->> 'investmentName',
    'sale_date', (p_request ->> 'saleDate')::date,
    'sold_share_count', (p_request ->> 'soldShareCount')::bigint,
    'proceeds', v_proceeds, 'cost_basis_reduction', v_cost,
    'gain_or_loss', v_proceeds - v_cost,
    'tax_treatment', p_prepared ->> 'taxTreatment',
    'remaining_share_count', (p_prepared ->> 'remainingShareCount')::bigint,
    'remaining_cost_basis', (p_prepared ->> 'remainingCostBasis')::numeric,
    'lot_allocations', (
      select coalesce(pg_catalog.jsonb_agg(item - 'expected_remaining_share_count'
        - 'expected_remaining_cost_basis'), '[]'::jsonb)
      from pg_catalog.jsonb_array_elements(v_allocations) item
    ),
    'bank_transaction_id', nullif(p_request ->> 'bankTransactionId', ''),
    'document_id', nullif(p_request ->> 'documentId', ''),
    'document_status', p_request ->> 'documentStatus'
  );
  perform pg_catalog.set_config('talli.investment_action_write', 'on', true);
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'share_sale',
    (p_request ->> 'saleDate')::date, v_payload, p_entry_id, v_bank_id,
    nullif(p_request ->> 'documentId', '')::uuid, 'ready', v_actor_id
  );
  insert into public.investment_lot_allocations (
    company_id, position_id, lot_id, sale_action_id,
    allocated_share_count, allocated_cost_basis, created_by
  ) select
    (p_request ->> 'companyId')::uuid, v_position_id,
    (item ->> 'lot_id')::uuid, v_action_id,
    (item ->> 'share_count')::bigint, (item ->> 'cost_basis')::numeric, v_actor_id
  from pg_catalog.jsonb_array_elements(v_allocations) item;
  update public.investment_positions
  set share_count = (p_prepared ->> 'remainingShareCount')::bigint,
      cost_basis = (p_prepared ->> 'remainingCostBasis')::numeric,
      movements = movements || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'action_id', v_action_id, 'movement_type', 'sale',
        'movement_date', (p_request ->> 'saleDate')::date,
        'share_delta', -(p_request ->> 'soldShareCount')::bigint,
        'cost_basis_delta', -v_cost, 'amount', v_proceeds,
        'gain_or_loss', v_proceeds - v_cost,
        'lot_allocations', v_payload -> 'lot_allocations'
      )), updated_at = pg_catalog.now()
  where id = v_position_id;
  if v_bank_id is not null then
    update public.bank_transactions set matched_action_id = v_action_id::text
    where id = v_bank_id and matched_action_id is null and matched_entry_id is null;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    (p_request ->> 'companyId')::uuid, v_actor_id, 'ledger',
    'share_sale_recorded', 'Aksjesalg postert for '
      || (p_prepared ->> 'investmentName') || ' i '
      || (p_request ->> 'incomeYear') || '.'
  );
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'actionId', v_action_id, 'positionId', v_position_id,
      'payload', v_payload, 'auditRequired', false
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_investment_sale_fifo', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.assert_fresh_corporate_step_up_v1(
  p_company_id uuid, p_verified_subject text
)
returns uuid language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_claims jsonb := public.company_access_auth_jwt_v1();
  v_mfa_verified_at timestamptz;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or coalesce(v_claims ->> 'sub', '') <> v_actor_id::text
    or coalesce(v_claims ->> 'aal', '') <> 'aal2'
    or pg_catalog.jsonb_typeof(v_claims -> 'amr') is distinct from 'array'
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'ledger_forbidden'; end if;
  select pg_catalog.to_timestamp((entry ->> 'timestamp')::double precision)
  into v_mfa_verified_at
  from pg_catalog.jsonb_array_elements(v_claims -> 'amr') entry
  where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
    and entry ->> 'timestamp' ~ '^[0-9]{1,12}$'
  order by (entry ->> 'timestamp')::bigint desc limit 1;
  if v_mfa_verified_at is null or v_mfa_verified_at > pg_catalog.now()
    or v_mfa_verified_at < pg_catalog.now() - interval '15 minutes'
  then raise exception 'ledger_forbidden'; end if;
  return v_actor_id;
end;
$function$;

create or replace function backend_system.prepare_corporate_decision_finalization_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_decision public.corporate_decisions%rowtype;
  v_existing public.corporate_decision_finalizations%rowtype;
  v_policy public.corporate_accounting_policies%rowtype;
  v_decision_id uuid := (p_request ->> 'decisionId')::uuid;
  v_set_id uuid := (p_request ->> 'setId')::uuid;
  v_finalization_id uuid := (p_request ->> 'finalizationId')::uuid;
  v_holding_action_id uuid := nullif(p_request ->> 'holdingActionId', '')::uuid;
  v_ledger_entry_id uuid := nullif(p_request ->> 'ledgerEntryId', '')::uuid;
  v_signed_hashes jsonb;
  v_signed_count integer;
  v_policy_count integer;
  v_amount numeric;
  v_primary_document_id uuid;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'finalize_corporate_decision', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  select finalization.* into v_existing
  from public.corporate_decision_finalizations finalization
  where finalization.decision_id = v_decision_id;
  if found then
    if v_existing.id <> v_finalization_id
      or v_existing.decision_hash <> p_request ->> 'decisionHash'
      or v_existing.holding_action_id is distinct from v_holding_action_id
      or v_existing.ledger_entry_id is distinct from v_ledger_entry_id
      or not exists (
        select 1 from public.corporate_document_events event
        where event.decision_id = v_decision_id and event.event_kind = 'finalized'
          and event.idempotency_key = p_request ->> 'idempotencyKey'
      )
    then raise exception 'ledger_idempotency_key_reused'; end if;
    if v_existing.ledger_entry_id is null then
      return pg_catalog.jsonb_build_object(
        'replay', pg_catalog.jsonb_build_object(
          'status', 'existing', 'companyId', v_existing.company_id,
          'incomeYear', v_existing.income_year, 'finalizationId', v_existing.id,
          'finalizationKind', v_existing.finalization_kind,
          'holdingActionId', v_existing.holding_action_id,
          'ledgerEntryId', null, 'auditRequired', false
        )
      );
    end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        v_existing.ledger_entry_id,
        pg_catalog.jsonb_build_object(
          'status', 'existing', 'finalizationId', v_existing.id,
          'finalizationKind', v_existing.finalization_kind,
          'holdingActionId', v_existing.holding_action_id,
          'ledgerEntryId', v_existing.ledger_entry_id, 'auditRequired', false
        )
      )
    );
  end if;
  select decision.* into v_decision from public.corporate_decisions decision
  where decision.id = v_decision_id for update;
  if not found or v_decision.company_id <> (p_request ->> 'companyId')::uuid
    or v_decision.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'ledger_invalid_input'; end if;
  perform backend_system.assert_fresh_corporate_step_up_v1(
    v_decision.company_id, p_verified_subject
  );
  if v_decision.decision_hash <> p_request ->> 'decisionHash'
    or not exists (
      select 1 from public.corporate_document_sets document_set
      where document_set.id = v_set_id and document_set.decision_id = v_decision.id
        and document_set.company_id = v_decision.company_id
        and document_set.income_year = v_decision.income_year
        and document_set.decision_hash = v_decision.decision_hash
    )
  then raise exception 'ledger_invalid_input'; end if;
  perform public.assert_corporate_decision_persisted_facts(
    v_decision.company_id, v_decision.income_year, v_decision.decision_kind,
    v_decision.annual_close_source_id, v_decision.canonical_input,
    v_decision.decision_hash
  );
  if not exists (
    select 1 from public.corporate_document_events event
    where event.decision_id = v_decision.id and event.event_kind = 'facts_approved'
      and event.decision_hash = v_decision.decision_hash
  ) or exists (
    select 1 from public.corporate_document_events event
    where event.decision_id = v_decision.id
      and event.event_kind in ('rejected', 'superseded')
  ) then raise exception 'ledger_invalid_input'; end if;
  select pg_catalog.count(*), pg_catalog.jsonb_object_agg(
    artifact.artifact_kind, artifact.content_sha256
  ) into v_signed_count, v_signed_hashes
  from public.corporate_document_artifacts artifact
  where artifact.set_id = v_set_id and artifact.variant = 'signed_owner_attested';
  if v_signed_count <> 2
    or (v_decision.decision_kind = 'owner_dividend' and not (
      v_signed_hashes ? 'dividend_board_proposal'
      and v_signed_hashes ? 'dividend_general_meeting_minutes'
    ))
    or (v_decision.decision_kind = 'annual_close' and not (
      v_signed_hashes ? 'annual_board_minutes'
      and v_signed_hashes ? 'annual_general_meeting_minutes'
    ))
  then raise exception 'ledger_invalid_input'; end if;
  if v_decision.decision_kind = 'annual_close' then
    if v_holding_action_id is not null or v_ledger_entry_id is not null
    then raise exception 'ledger_invalid_input'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', null, 'decisionKind', 'annual_close',
      'signedArtifactHashes', v_signed_hashes,
      'annualCloseSourceId', v_decision.annual_close_source_id
    );
  end if;
  if v_holding_action_id is null or v_ledger_entry_id is null
  then raise exception 'ledger_invalid_input'; end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select pg_catalog.count(*) into v_policy_count
  from public.corporate_accounting_policies policy
  where policy.enabled and not exists (
    select 1 from public.corporate_accounting_policies successor
    where successor.enabled and successor.supersedes_policy_version = policy.policy_version
  );
  if v_policy_count <> 1 then raise exception 'ledger_invalid_input'; end if;
  select policy.* into v_policy from public.corporate_accounting_policies policy
  where policy.enabled and not exists (
    select 1 from public.corporate_accounting_policies successor
    where successor.enabled and successor.supersedes_policy_version = policy.policy_version
  ) order by policy.reviewed_at desc, policy.policy_version limit 1;
  v_amount := ((v_decision.canonical_input -> 'dividend' ->> 'amount_ore')::numeric / 100);
  if v_amount <= 0 then raise exception 'ledger_invalid_input'; end if;
  select artifact.document_id into v_primary_document_id
  from public.corporate_document_artifacts artifact
  where artifact.set_id = v_set_id and artifact.variant = 'signed_owner_attested'
    and artifact.artifact_kind = 'dividend_general_meeting_minutes';
  return pg_catalog.jsonb_build_object(
    'replay', null, 'decisionKind', 'owner_dividend',
    'declaredAmount', v_amount,
    'declarationDebitAccount', v_policy.declaration_debit_account,
    'dividendPayableAccount', v_policy.dividend_payable_account,
    'bankAccount', v_policy.bank_account,
    'accountingPolicyVersion', v_policy.policy_version,
    'signedArtifactHashes', v_signed_hashes,
    'primaryDocumentId', v_primary_document_id,
    'actionDate', v_decision.canonical_input -> 'general_meeting' ->> 'meeting_date',
    'canonicalInput', v_decision.canonical_input
  );
end;
$function$;

create or replace function backend_system.complete_corporate_decision_finalization_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_decision_id uuid := (p_request ->> 'decisionId')::uuid;
  v_set_id uuid := (p_request ->> 'setId')::uuid;
  v_finalization_id uuid := (p_request ->> 'finalizationId')::uuid;
  v_holding_action_id uuid := nullif(p_request ->> 'holdingActionId', '')::uuid;
  v_existing public.corporate_decision_finalizations%rowtype;
  v_result jsonb;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or p_prepared ->> 'decisionKind' not in ('owner_dividend', 'annual_close')
  then raise exception 'ledger_dependency_unavailable'; end if;
  if p_prepared ->> 'decisionKind' = 'owner_dividend' then
    if p_entry_id is null or p_entry_id is distinct from (p_request ->> 'ledgerEntryId')::uuid
      or not exists (
        select 1 from ledger.entries entry where entry.id = p_entry_id
          and entry.entry_kind = 'OWNER_DIVIDEND_DECLARED'
          and entry.source_record_id = p_request ->> 'finalizationId'
      )
    then raise exception 'ledger_dependency_unavailable'; end if;
    insert into public.holding_actions (
      id, company_id, income_year, action_type, action_date, payload,
      ledger_entry_id, document_id, risk_level, created_by
    ) values (
      v_holding_action_id, (p_request ->> 'companyId')::uuid,
      (p_request ->> 'incomeYear')::integer, 'dividend_to_owner',
      (p_prepared ->> 'actionDate')::date,
      (p_prepared -> 'canonicalInput') || pg_catalog.jsonb_build_object(
        'action_kind', 'owner_dividend_declaration',
        'corporate_decision_id', v_decision_id,
        'accounting_policy_version', p_prepared ->> 'accountingPolicyVersion'
      ), p_entry_id, (p_prepared ->> 'primaryDocumentId')::uuid, 'ready', v_actor_id
    );
    insert into public.corporate_decision_finalizations (
      id, company_id, income_year, decision_id, finalization_kind,
      holding_action_id, ledger_entry_id, decision_hash, signed_artifact_hashes,
      accounting_policy_version, created_by
    ) values (
      v_finalization_id, (p_request ->> 'companyId')::uuid,
      (p_request ->> 'incomeYear')::integer, v_decision_id,
      'owner_dividend_declared', v_holding_action_id, p_entry_id,
      p_request ->> 'decisionHash', p_prepared -> 'signedArtifactHashes',
      p_prepared ->> 'accountingPolicyVersion', v_actor_id
    ) returning * into v_existing;
  else
    if p_entry_id is not null or v_holding_action_id is not null
    then raise exception 'ledger_invalid_input'; end if;
    insert into public.corporate_decision_finalizations (
      id, company_id, income_year, decision_id, finalization_kind,
      annual_close_source_id, decision_hash, signed_artifact_hashes, created_by
    ) values (
      v_finalization_id, (p_request ->> 'companyId')::uuid,
      (p_request ->> 'incomeYear')::integer, v_decision_id,
      'annual_close_adopted', (p_prepared ->> 'annualCloseSourceId')::uuid,
      p_request ->> 'decisionHash', p_prepared -> 'signedArtifactHashes', v_actor_id
    ) returning * into v_existing;
  end if;
  insert into public.corporate_document_events (
    company_id, income_year, decision_id, set_id, event_kind, actor_id,
    decision_hash, metadata, idempotency_key
  ) values (
    v_existing.company_id, v_existing.income_year, v_decision_id, v_set_id,
    'finalized', v_actor_id, p_request ->> 'decisionHash',
    pg_catalog.jsonb_build_object(
      'finalization_id', v_existing.id,
      'finalization_kind', v_existing.finalization_kind,
      'signed_artifact_hashes', p_prepared -> 'signedArtifactHashes',
      'accounting_policy_version', v_existing.accounting_policy_version
    ), p_request ->> 'idempotencyKey'
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_existing.company_id, v_actor_id, 'corporate_documents',
    'corporate_decision_finalized',
    'Owner finalized an approved and owner-attested corporate decision.'
  );
  if p_entry_id is null then
    v_result := pg_catalog.jsonb_build_object(
      'status', 'created', 'companyId', v_existing.company_id,
      'incomeYear', v_existing.income_year, 'finalizationId', v_existing.id,
      'finalizationKind', v_existing.finalization_kind,
      'holdingActionId', null, 'ledgerEntryId', null, 'auditRequired', false
    );
  else
    v_result := backend_system.ledger_writer_entry_result_v1(
      p_entry_id,
      pg_catalog.jsonb_build_object(
        'status', 'created', 'finalizationId', v_existing.id,
        'finalizationKind', v_existing.finalization_kind,
        'holdingActionId', v_existing.holding_action_id,
        'ledgerEntryId', p_entry_id,
        'accountingPolicyVersion', v_existing.accounting_policy_version,
        'auditRequired', false
      )
    );
  end if;
  return backend_system.complete_ledger_writer_v1(
    'finalize_corporate_decision', p_request, v_result, p_verified_subject
  );
end;
$function$;

create or replace function backend_system.prepare_owner_dividend_payment_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_decision public.corporate_decisions%rowtype;
  v_finalization public.corporate_decision_finalizations%rowtype;
  v_policy public.corporate_accounting_policies%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_existing public.corporate_document_events%rowtype;
  v_decision_id uuid := (p_request ->> 'decisionId')::uuid;
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_declared_ore bigint;
  v_paid_ore bigint;
  v_payment_ore bigint;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'record_owner_dividend_payment', p_request, p_verified_subject
  );
  if v_replay is not null then return pg_catalog.jsonb_build_object('replay', v_replay); end if;
  select event.* into v_existing from public.corporate_document_events event
  where event.idempotency_key = p_request ->> 'idempotencyKey';
  if found then
    if v_existing.decision_id <> v_decision_id
      or v_existing.set_id <> (p_request ->> 'setId')::uuid
      or v_existing.event_kind <> 'payment_recorded'
      or v_existing.decision_hash <> p_request ->> 'decisionHash'
      or v_existing.metadata ->> 'bank_transaction_id' <> p_request ->> 'bankTransactionId'
      or v_existing.metadata ->> 'holding_action_id' <> p_request ->> 'holdingActionId'
      or v_existing.metadata ->> 'ledger_entry_id' <> p_request ->> 'ledgerEntryId'
    then raise exception 'ledger_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'replay', backend_system.ledger_writer_entry_result_v1(
        (p_request ->> 'ledgerEntryId')::uuid,
        pg_catalog.jsonb_build_object(
          'status', 'existing', 'eventId', v_existing.id,
          'holdingActionId', p_request ->> 'holdingActionId',
          'remainingPayableOre', (v_existing.metadata ->> 'remaining_payable_ore')::bigint,
          'auditRequired', false
        )
      )
    );
  end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select decision.* into v_decision from public.corporate_decisions decision
  where decision.id = v_decision_id for update;
  if not found or v_decision.decision_kind <> 'owner_dividend'
    or v_decision.company_id <> (p_request ->> 'companyId')::uuid
    or v_decision.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'ledger_invalid_input'; end if;
  perform backend_system.assert_fresh_corporate_step_up_v1(
    v_decision.company_id, p_verified_subject
  );
  if v_decision.decision_hash <> p_request ->> 'decisionHash'
    or not exists (
      select 1 from public.corporate_document_sets document_set
      where document_set.id = (p_request ->> 'setId')::uuid
        and document_set.decision_id = v_decision.id
        and document_set.decision_hash = v_decision.decision_hash
    )
  then raise exception 'ledger_invalid_input'; end if;
  select finalization.* into v_finalization
  from public.corporate_decision_finalizations finalization
  where finalization.decision_id = v_decision.id
    and finalization.finalization_kind = 'owner_dividend_declared' for share;
  if not found then raise exception 'ledger_invalid_input'; end if;
  select policy.* into v_policy from public.corporate_accounting_policies policy
  where policy.policy_version = v_finalization.accounting_policy_version;
  if not found then raise exception 'ledger_invalid_input'; end if;
  select bank.* into v_bank from public.bank_transactions bank
  where bank.id = v_bank_id for update;
  if not found or v_bank.company_id <> v_decision.company_id
    or v_bank.income_year <> v_decision.income_year
    or v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
    or v_bank.amount >= 0 or v_bank.amount <> pg_catalog.round(v_bank.amount, 2)
  then raise exception 'ledger_invalid_input'; end if;
  v_declared_ore := (v_decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint;
  select coalesce(pg_catalog.sum((event.metadata ->> 'amount_ore')::bigint), 0)
  into v_paid_ore from public.corporate_document_events event
  where event.decision_id = v_decision.id and event.event_kind = 'payment_recorded';
  v_payment_ore := pg_catalog.round(pg_catalog.abs(v_bank.amount) * 100)::bigint;
  if v_payment_ore <= 0 or v_payment_ore > v_declared_ore - v_paid_ore
  then raise exception 'ledger_invalid_input'; end if;
  return pg_catalog.jsonb_build_object(
    'replay', null, 'paymentAmount', v_payment_ore::numeric / 100,
    'paymentOre', v_payment_ore,
    'remainingPayableOre', v_declared_ore - v_paid_ore - v_payment_ore,
    'transactionDate', v_bank.transaction_date,
    'finalizationId', v_finalization.id,
    'dividendPayableAccount', v_policy.dividend_payable_account,
    'bankAccount', v_policy.bank_account,
    'accountingPolicyVersion', v_policy.policy_version
  );
end;
$function$;

create or replace function backend_system.complete_owner_dividend_payment_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_action_id uuid := (p_request ->> 'holdingActionId')::uuid;
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_event public.corporate_document_events%rowtype;
  v_result jsonb;
begin
  if v_actor_id is distinct from p_verified_subject::uuid
    or p_entry_id is distinct from (p_request ->> 'ledgerEntryId')::uuid
    or not exists (
      select 1 from ledger.entries entry where entry.id = p_entry_id
        and entry.entry_kind = 'OWNER_DIVIDEND_PAYMENT'
        and entry.source_record_id = p_request ->> 'holdingActionId'
    )
  then raise exception 'ledger_dependency_unavailable'; end if;
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, risk_level, created_by
  ) values (
    v_action_id, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, 'dividend_to_owner',
    (p_prepared ->> 'transactionDate')::date,
    pg_catalog.jsonb_build_object(
      'action_kind', 'owner_dividend_payment',
      'corporate_decision_id', (p_request ->> 'decisionId')::uuid,
      'corporate_finalization_id', (p_prepared ->> 'finalizationId')::uuid,
      'amount_ore', (p_prepared ->> 'paymentOre')::bigint,
      'remaining_payable_ore', (p_prepared ->> 'remainingPayableOre')::bigint,
      'accounting_policy_version', p_prepared ->> 'accountingPolicyVersion'
    ), p_entry_id, v_bank_id, 'ready', v_actor_id
  );
  update public.bank_transactions
  set matched_entry_id = p_entry_id, matched_action_id = v_action_id::text
  where id = v_bank_id and matched_entry_id is null and matched_action_id is null;
  if not found then raise exception 'ledger_idempotency_key_reused'; end if;
  insert into public.corporate_document_events (
    company_id, income_year, decision_id, set_id, event_kind, actor_id,
    decision_hash, metadata, idempotency_key
  ) values (
    (p_request ->> 'companyId')::uuid, (p_request ->> 'incomeYear')::integer,
    (p_request ->> 'decisionId')::uuid, (p_request ->> 'setId')::uuid,
    'payment_recorded', v_actor_id, p_request ->> 'decisionHash',
    pg_catalog.jsonb_build_object(
      'bank_transaction_id', v_bank_id, 'holding_action_id', v_action_id,
      'ledger_entry_id', p_entry_id,
      'amount_ore', (p_prepared ->> 'paymentOre')::bigint,
      'remaining_payable_ore', (p_prepared ->> 'remainingPayableOre')::bigint,
      'accounting_policy_version', p_prepared ->> 'accountingPolicyVersion'
    ), p_request ->> 'idempotencyKey'
  ) returning * into v_event;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    (p_request ->> 'companyId')::uuid, v_actor_id, 'corporate_documents',
    'owner_dividend_payment_recorded',
    'Bank payment matched to finalized owner dividend payable.'
  );
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'status', 'created', 'eventId', v_event.id,
      'holdingActionId', v_action_id,
      'remainingPayableOre', (p_prepared ->> 'remainingPayableOre')::bigint,
      'auditRequired', false
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'record_owner_dividend_payment', p_request, v_result, p_verified_subject
  );
end;
$function$;

revoke all on function
  backend_system.claim_ledger_writer_v1(text, jsonb, text),
  backend_system.complete_ledger_writer_v1(text, jsonb, jsonb, text),
  backend_system.ledger_writer_entry_result_v1(uuid, jsonb),
  backend_system.lock_ledger_writer_year_v1(jsonb),
  backend_system.assert_fresh_corporate_step_up_v1(uuid, text),
  backend_system.prepare_administrative_cost_v1(jsonb, text),
  backend_system.complete_administrative_cost_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_dividend_v1(jsonb, text),
  backend_system.complete_investment_dividend_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_shareholder_loan_v1(jsonb, text),
  backend_system.complete_shareholder_loan_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_tax_settlement_v1(jsonb, text),
  backend_system.complete_tax_settlement_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_purchase_fifo_v1(jsonb, text),
  backend_system.complete_investment_purchase_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_sale_fifo_v1(jsonb, text),
  backend_system.complete_investment_sale_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_corporate_decision_finalization_v1(jsonb, text),
  backend_system.complete_corporate_decision_finalization_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_owner_dividend_payment_v1(jsonb, text),
  backend_system.complete_owner_dividend_payment_v1(jsonb, uuid, jsonb, text),
  ledger.post_entry_with_id_v1(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text, uuid
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;

grant execute on function
  backend_system.prepare_administrative_cost_v1(jsonb, text),
  backend_system.complete_administrative_cost_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_dividend_v1(jsonb, text),
  backend_system.complete_investment_dividend_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_shareholder_loan_v1(jsonb, text),
  backend_system.complete_shareholder_loan_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_tax_settlement_v1(jsonb, text),
  backend_system.complete_tax_settlement_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_purchase_fifo_v1(jsonb, text),
  backend_system.complete_investment_purchase_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_sale_fifo_v1(jsonb, text),
  backend_system.complete_investment_sale_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_corporate_decision_finalization_v1(jsonb, text),
  backend_system.complete_corporate_decision_finalization_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_owner_dividend_payment_v1(jsonb, text),
  backend_system.complete_owner_dividend_payment_v1(jsonb, uuid, jsonb, text),
  ledger.post_entry_with_id_v1(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text, uuid
  )
to ledger_workflow_executor;

do $ledger_writer_migration_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema ledger, backend_system from %I', current_user
  );
  execute pg_catalog.format(
    'revoke ledger_store_owner, ledger_workflow_store_owner from %I', current_user
  );
end
$ledger_writer_migration_membership_revoke$;

commit;
