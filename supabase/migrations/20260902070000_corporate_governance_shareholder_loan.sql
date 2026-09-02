-- Canonical shareholder-loan governance workflow (#145).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor, '
      || 'corporate_governance_ledger_bridge_owner, '
      || 'banking_store_owner, ledger_store_owner to %I',
    current_user
  );
end
$membership$;

create table corporate_governance.shareholder_loans (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  loan_date date not null,
  amount_ore bigint not null check (amount_ore > 0),
  direction text not null check (direction in (
    'shareholder_to_company', 'company_to_corporate_shareholder'
  )),
  counterparty_name text not null check (
    pg_catalog.btrim(counterparty_name) <> ''
    and pg_catalog.char_length(counterparty_name) <= 255
  ),
  document_status text not null check (document_status in (
    'attached', 'missing_accepted_warning', 'not_required'
  )),
  interest_modelled boolean not null,
  related_party_security boolean not null check (not related_party_security),
  bank_transaction_id uuid unique references banking.transactions(id)
    on delete restrict,
  document_id uuid,
  accounting_entry_id uuid not null unique references ledger.entries(id)
    on delete restrict,
  bank_transaction_date date,
  bank_signed_amount numeric(20, 2),
  bank_source_sha256 text,
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  correlation_id text not null check (
    pg_catalog.btrim(correlation_id) <> ''
    and pg_catalog.char_length(correlation_id) <= 255
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  legacy_imported boolean not null default false,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (created_by, company_id, idempotency_key),
  unique (company_id, income_year, action_id),
  check (extract(year from loan_date)::integer = income_year),
  check (
    (bank_transaction_id is null and bank_transaction_date is null
      and bank_signed_amount is null and bank_source_sha256 is null)
    or
    (bank_transaction_id is not null and bank_transaction_date is not null
      and bank_signed_amount is not null
      and bank_source_sha256 ~ '^[0-9a-f]{64}$')
  ),
  check (
    bank_signed_amount is null
    or (direction = 'shareholder_to_company' and bank_signed_amount > 0)
    or (direction = 'company_to_corporate_shareholder'
      and bank_signed_amount < 0)
  )
);

alter table corporate_governance.shareholder_loans
  owner to corporate_governance_store_owner;
revoke all on corporate_governance.shareholder_loans
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

reset role;

-- The migration principal performs the one-time expansion while RLS is off.
insert into corporate_governance.shareholder_loans (
  action_id, company_id, income_year, loan_date, amount_ore, direction,
  counterparty_name, document_status, interest_modelled,
  related_party_security, bank_transaction_id, document_id,
  accounting_entry_id, bank_transaction_date, bank_signed_amount,
  bank_source_sha256, idempotency_key, correlation_id,
  request_fingerprint, legacy_imported, created_by, created_at
)
select
  action.id, action.company_id, action.income_year, action.action_date,
  pg_catalog.round((action.payload ->> 'amount')::numeric * 100)::bigint,
  action.payload ->> 'direction',
  pg_catalog.btrim(action.payload ->> 'counterparty_name'),
  action.payload ->> 'document_status',
  coalesce((action.payload ->> 'interest_modelled')::boolean, false),
  false, action.bank_transaction_id, action.document_id,
  action.ledger_entry_id, transaction.transaction_date, transaction.amount,
  transaction.source_hash,
  'legacy-import-' || pg_catalog.replace(action.id::text, '-', ''),
  'legacy-import:' || action.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'actionId', action.id,
    'companyId', action.company_id,
    'incomeYear', action.income_year,
    'ledgerEntryId', action.ledger_entry_id,
    'loanDate', action.action_date,
    'amountOre', pg_catalog.round(
      (action.payload ->> 'amount')::numeric * 100
    )::bigint,
    'direction', action.payload ->> 'direction',
    'counterpartyName', pg_catalog.btrim(
      action.payload ->> 'counterparty_name'
    )
  )::text, 'sha256'), 'hex'),
  true, action.created_by, action.created_at
from public.holding_actions action
left join banking.transactions transaction
  on transaction.id = action.bank_transaction_id
where action.action_type = 'shareholder_loan';

set local role corporate_governance_store_owner;

alter table corporate_governance.shareholder_loans enable row level security;
alter table corporate_governance.shareholder_loans force row level security;

create policy governance_owner_reads_shareholder_loans
on corporate_governance.shareholder_loans
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_shareholder_loans
on corporate_governance.shareholder_loans
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create trigger shareholder_loans_immutable
before update or delete on corporate_governance.shareholder_loans
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

create or replace function corporate_governance.shareholder_loan_result_v1(
  p_action_id uuid,
  p_replayed boolean
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_loan corporate_governance.shareholder_loans%rowtype;
begin
  select loan.* into v_loan
  from corporate_governance.shareholder_loans loan
  where loan.action_id = p_action_id;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  return pg_catalog.jsonb_build_object(
    'loan', pg_catalog.jsonb_build_object(
      'actionId', v_loan.action_id,
      'companyId', v_loan.company_id,
      'incomeYear', v_loan.income_year,
      'loanDate', v_loan.loan_date,
      'amountOre', v_loan.amount_ore,
      'direction', v_loan.direction,
      'counterpartyName', v_loan.counterparty_name,
      'documentStatus', v_loan.document_status,
      'interestModelled', v_loan.interest_modelled,
      'relatedPartySecurity', v_loan.related_party_security,
      'bankTransactionId', v_loan.bank_transaction_id,
      'documentId', v_loan.document_id
    ),
    'accountingEntryId', v_loan.accounting_entry_id,
    'replayed', p_replayed
  );
end;
$function$;

reset role;

-- Banking owns inspection and claim of the exact locked bank fact.
grant usage, create on schema banking to banking_store_owner;
set local role banking_store_owner;

create or replace function banking.prepare_shareholder_loan_transaction_v1(
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
  v_transaction banking.transactions%rowtype;
  v_company_id uuid;
  v_income_year integer;
  v_expected_amount numeric;
begin
  if v_actor_id is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'banking_forbidden';
  end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_expected_amount := (p_request ->> 'amountOre')::bigint / 100.0;
    if p_request ->> 'direction' = 'company_to_corporate_shareholder' then
      v_expected_amount := -v_expected_amount;
    elsif p_request ->> 'direction' <> 'shareholder_to_company' then
      raise exception 'banking_invalid_input';
    end if;
    select transaction.* into v_transaction
    from banking.transactions transaction
    where transaction.id = (p_request ->> 'bankTransactionId')::uuid
      and transaction.company_id = v_company_id
      and transaction.income_year = v_income_year
    for update;
  exception when invalid_text_representation or numeric_value_out_of_range then
    raise exception 'banking_invalid_input';
  end;
  if not public.company_access_company_year_allows_consequential_v1(
    v_company_id, v_income_year
  ) then
    raise exception 'banking_forbidden';
  end if;
  if not found then
    raise exception 'banking_transaction_not_found';
  end if;
  if v_transaction.matched_accounting_entry_id is not null
    or v_transaction.matched_action_reference is not null
    or v_transaction.warning_accepted
  then
    raise exception 'banking_transaction_already_reconciled';
  end if;
  if v_transaction.amount <> v_expected_amount
    or v_transaction.amount <> pg_catalog.round(v_transaction.amount, 2)
  then
    raise exception 'banking_transaction_fact_mismatch';
  end if;
  return pg_catalog.jsonb_build_object(
    'bankTransactionDate', v_transaction.transaction_date,
    'bankSignedAmount', v_transaction.amount,
    'bankSourceSha256', v_transaction.source_hash
  );
end;
$function$;

create or replace function banking.claim_corporate_governance_transaction_v1(
  p_request jsonb,
  p_accounting_entry_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if coalesce(p_request ->> 'actionReference', '')
      !~ '^[0-9a-fA-F-]{36}$'
  then
    raise exception 'banking_invalid_input';
  end if;
  return banking.claim_transaction_for_external_action_v1(
    p_request, p_accounting_entry_id, p_verified_subject
  );
end;
$function$;

reset role;
revoke create on schema banking from banking_store_owner;
grant usage on schema banking to corporate_governance_store_owner;
grant execute on function banking.prepare_shareholder_loan_transaction_v1(
  jsonb, text
) to corporate_governance_store_owner;
grant usage on schema banking to corporate_governance_workflow_executor;
grant execute on function banking.claim_corporate_governance_transaction_v1(
  jsonb, uuid, text
) to corporate_governance_workflow_executor;

-- The projection keeps the predecessor read model complete for rollback.
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;

create or replace function backend_system.project_shareholder_loan_v1(
  p_request jsonb,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_existing public.holding_actions%rowtype;
begin
  if v_actor_id is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  select action.* into v_existing
  from public.holding_actions action
  where action.id = (p_request ->> 'actionId')::uuid;
  if found then
    if v_existing.company_id <> (p_request ->> 'companyId')::uuid
      or v_existing.income_year <> (p_request ->> 'incomeYear')::integer
      or v_existing.action_type <> 'shareholder_loan'
      or v_existing.ledger_entry_id <> (p_request ->> 'ledgerEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return;
  end if;
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, document_id, risk_level, created_by
  ) values (
    (p_request ->> 'actionId')::uuid,
    (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer,
    'shareholder_loan', (p_request ->> 'loanDate')::date,
    pg_catalog.jsonb_build_object(
      'loan_date', (p_request ->> 'loanDate')::date,
      'amount', (p_request ->> 'amountOre')::bigint / 100.0,
      'direction', p_request ->> 'direction',
      'counterparty_name', p_request ->> 'counterpartyName',
      'document_status', p_request ->> 'documentStatus',
      'interest_modelled', (p_request ->> 'interestModelled')::boolean,
      'related_party_security', false,
      'bank_transaction_id', p_request -> 'bankTransactionId',
      'document_id', p_request -> 'documentId'
    ),
    (p_request ->> 'ledgerEntryId')::uuid,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    'ready', v_actor_id
  );
end;
$function$;

revoke create on schema backend_system from ledger_store_owner;
reset role;
grant execute on function backend_system.project_shareholder_loan_v1(
  jsonb, text
) to corporate_governance_store_owner;

set local role corporate_governance_store_owner;

create or replace function corporate_governance.prepare_shareholder_loan_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_existing corporate_governance.shareholder_loans%rowtype;
  v_bank jsonb;
  v_fingerprint text;
  v_company_id uuid;
  v_income_year integer;
  v_action_id uuid;
begin
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_action_id := (p_request ->> 'actionId')::uuid;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_company_id, v_income_year, p_verified_subject, true
  );
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'talli:corporate-governance:shareholder-loan:'
      || v_company_id::text || ':' || v_income_year::text, 0
  ));
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select loan.* into v_existing
  from corporate_governance.shareholder_loans loan
  where loan.action_id = v_action_id
    or (loan.created_by = v_actor_id
      and loan.company_id = v_company_id
      and loan.idempotency_key = p_request ->> 'idempotencyKey')
  order by (loan.action_id = v_action_id) desc
  limit 1;
  if found then
    if (not v_existing.legacy_imported
        and v_existing.request_fingerprint <> v_fingerprint)
      or v_existing.company_id <> v_company_id
      or v_existing.income_year <> v_income_year
      or v_existing.accounting_entry_id
        <> (p_request ->> 'ledgerEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return pg_catalog.jsonb_build_object(
      'loan', corporate_governance.shareholder_loan_result_v1(
        v_existing.action_id, true
      ) -> 'loan',
      'bankTransactionDate', v_existing.bank_transaction_date,
      'bankSignedAmount', v_existing.bank_signed_amount,
      'bankSourceSha256', v_existing.bank_source_sha256,
      'replay', corporate_governance.shareholder_loan_result_v1(
        v_existing.action_id, true
      )
    );
  end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_request ->> 'correlationId', '')) = ''
    or (p_request ->> 'ledgerEntryId') !~ '^[0-9a-fA-F-]{36}$'
    or (p_request ->> 'amountOre')::bigint <= 0
    or extract(year from (p_request ->> 'loanDate')::date)::integer
      <> v_income_year
    or p_request ->> 'direction' not in (
      'shareholder_to_company', 'company_to_corporate_shareholder'
    )
    or pg_catalog.btrim(coalesce(p_request ->> 'counterpartyName', '')) = ''
    or pg_catalog.char_length(p_request ->> 'counterpartyName') > 255
    or p_request ->> 'documentStatus' not in (
      'attached', 'missing_accepted_warning', 'not_required'
    )
    or coalesce((p_request ->> 'relatedPartySecurity')::boolean, false)
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  if nullif(p_request ->> 'bankTransactionId', '') is not null then
    v_bank := banking.prepare_shareholder_loan_transaction_v1(
      p_request, p_verified_subject
    );
  end if;
  return pg_catalog.jsonb_build_object(
    'loan', pg_catalog.jsonb_build_object(
      'actionId', v_action_id,
      'companyId', v_company_id,
      'incomeYear', v_income_year,
      'loanDate', (p_request ->> 'loanDate')::date,
      'amountOre', (p_request ->> 'amountOre')::bigint,
      'direction', p_request ->> 'direction',
      'counterpartyName', pg_catalog.btrim(p_request ->> 'counterpartyName'),
      'documentStatus', p_request ->> 'documentStatus',
      'interestModelled', coalesce(
        (p_request ->> 'interestModelled')::boolean, false
      ),
      'relatedPartySecurity', false,
      'bankTransactionId', nullif(p_request ->> 'bankTransactionId', '')::uuid,
      'documentId', nullif(p_request ->> 'documentId', '')::uuid
    ),
    'bankTransactionDate', v_bank -> 'bankTransactionDate',
    'bankSignedAmount', v_bank -> 'bankSignedAmount',
    'bankSourceSha256', v_bank -> 'bankSourceSha256',
    'replay', null
  );
exception when invalid_text_representation or numeric_value_out_of_range
  or datetime_field_overflow then
  raise exception 'corporate_governance_invalid_input';
end;
$function$;

create or replace function corporate_governance.complete_shareholder_loan_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_existing corporate_governance.shareholder_loans%rowtype;
  v_fingerprint text;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_action_id uuid := (p_request ->> 'actionId')::uuid;
begin
  v_actor_id := corporate_governance.assert_owner_v1(
    v_company_id, v_income_year, p_verified_subject, true
  );
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'talli:corporate-governance:shareholder-loan:'
      || v_company_id::text || ':' || v_income_year::text, 0
  ));
  v_fingerprint := corporate_governance.request_fingerprint_v1(
    p_request - 'bankTransactionDate' - 'bankSignedAmount'
      - 'bankSourceSha256'
  );
  select loan.* into v_existing
  from corporate_governance.shareholder_loans loan
  where loan.action_id = v_action_id
    or (loan.created_by = v_actor_id
      and loan.company_id = v_company_id
      and loan.idempotency_key = p_request ->> 'idempotencyKey')
  order by (loan.action_id = v_action_id) desc
  limit 1;
  if found then
    if (not v_existing.legacy_imported
        and v_existing.request_fingerprint <> v_fingerprint)
      or v_existing.accounting_entry_id
        <> (p_request ->> 'ledgerEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.shareholder_loan_result_v1(
      v_existing.action_id, true
    );
  end if;
  if not exists (
    select 1 from ledger.entries entry
    where entry.id = (p_request ->> 'ledgerEntryId')::uuid
      and entry.company_id = v_company_id
      and entry.income_year = v_income_year
      and entry.entry_kind = 'SHAREHOLDER_LOAN'
      and entry.source_capability = 'CORPORATE_GOVERNANCE'
      and entry.source_record_id = v_action_id::text
  ) then
    raise exception 'corporate_governance_dependency_unavailable';
  end if;
  if nullif(p_request ->> 'bankTransactionId', '') is null
    and (p_request -> 'bankTransactionDate' <> 'null'::jsonb
      or p_request -> 'bankSignedAmount' <> 'null'::jsonb
      or p_request -> 'bankSourceSha256' <> 'null'::jsonb)
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.shareholder_loans (
    action_id, company_id, income_year, loan_date, amount_ore, direction,
    counterparty_name, document_status, interest_modelled,
    related_party_security, bank_transaction_id, document_id,
    accounting_entry_id, bank_transaction_date, bank_signed_amount,
    bank_source_sha256, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    v_action_id, v_company_id, v_income_year,
    (p_request ->> 'loanDate')::date,
    (p_request ->> 'amountOre')::bigint,
    p_request ->> 'direction',
    pg_catalog.btrim(p_request ->> 'counterpartyName'),
    p_request ->> 'documentStatus',
    coalesce((p_request ->> 'interestModelled')::boolean, false),
    false, nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    (p_request ->> 'ledgerEntryId')::uuid,
    nullif(p_request ->> 'bankTransactionDate', '')::date,
    nullif(p_request ->> 'bankSignedAmount', '')::numeric,
    nullif(p_request ->> 'bankSourceSha256', ''),
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  perform backend_system.project_shareholder_loan_v1(
    p_request, p_verified_subject
  );
  return corporate_governance.shareholder_loan_result_v1(
    v_action_id, false
  );
exception when invalid_text_representation or numeric_value_out_of_range
  or datetime_field_overflow then
  raise exception 'corporate_governance_invalid_input';
end;
$function$;

reset role;

-- Expand the already-narrow governance ledger bridge by one characterized kind.
grant usage, create on schema ledger
to corporate_governance_ledger_bridge_owner;
set local role corporate_governance_ledger_bridge_owner;

create or replace function ledger.post_corporate_governance_entry_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
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
begin
  if pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT',
      'SHAREHOLDER_LOAN'
    )
    or p_source_capability <> 'CORPORATE_GOVERNANCE'
    or coalesce(p_source_record_id, '') !~ '^[0-9a-fA-F-]{36}$'
  then
    raise exception 'ledger_invalid_input';
  end if;
  return query select * from ledger.post_entry_with_id_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind,
    p_memo, p_lines, '[]'::jsonb, false, p_source_capability,
    p_source_record_id, p_correlation_id, p_verified_subject,
    p_requested_entry_id
  );
end;
$function$;

reset role;
revoke create on schema ledger
from corporate_governance_ledger_bridge_owner;

revoke all on function
  corporate_governance.shareholder_loan_result_v1(uuid, boolean),
  corporate_governance.prepare_shareholder_loan_v1(jsonb, text),
  corporate_governance.complete_shareholder_loan_v1(jsonb, text),
  banking.prepare_shareholder_loan_transaction_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on function banking.claim_corporate_governance_transaction_v1(
  jsonb, uuid, text
) from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, talli_banking_backend;
grant execute on function
  corporate_governance.prepare_shareholder_loan_v1(jsonb, text),
  corporate_governance.complete_shareholder_loan_v1(jsonb, text)
to corporate_governance_workflow_executor;
grant execute on function banking.claim_corporate_governance_transaction_v1(
  jsonb, uuid, text
) to corporate_governance_workflow_executor;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor, '
      || 'corporate_governance_ledger_bridge_owner, '
      || 'banking_store_owner, ledger_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
