-- Issue #191: append-only full reversal for the supported governance entries.
-- The writer mechanically swaps the stored debit and credit lines. It never
-- selects accounts or invents a replacement transaction.

begin;

do $authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$authority$;

alter table backend_system.ledger_command_receipts
  drop constraint if exists ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check check (
    operation_name in (
      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',
      'close_company_year', 'reverse_supported_entry'
    )
  );

create table ledger.entry_reversals (
  original_entry_id uuid primary key,
  reversal_entry_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  reason text not null check (
    pg_catalog.btrim(reason) <> '' and pg_catalog.length(reason) <= 500
  ),
  reversed_by uuid not null references auth.users(id) on delete restrict,
  reversed_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (original_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  foreign key (reversal_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (original_entry_id <> reversal_entry_id)
);

alter table ledger.entry_reversals owner to ledger_store_owner;
alter table ledger.entry_reversals enable row level security;
alter table ledger.entry_reversals force row level security;

set local role ledger_store_owner;

create policy "ledger store reads supported entry reversals"
on ledger.entry_reversals for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy "ledger store records supported entry reversals"
on ledger.entry_reversals for insert to ledger_store_owner
with check (
  reversed_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

create trigger ledger_entry_reversals_immutable
before update or delete on ledger.entry_reversals
for each row execute function backend_system.prevent_ledger_technical_mutation();

create or replace function ledger.reverse_supported_entry_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_original_entry_id uuid,
  p_reason text,
  p_correlation_id text,
  p_verified_subject text,
  p_event_date date,
  p_correction_source jsonb
)
returns table (
  original_entry_id uuid,
  reversal_entry_id uuid,
  company_id uuid,
  income_year integer,
  reversed_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_original ledger.entries%rowtype;
  v_reversal_id uuid;
  v_reversed_at timestamptz;
  v_lines jsonb;
  v_original_digest text;
  v_sources jsonb;
  v_sources_digest text;
  v_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null
    or p_original_entry_id is null
    or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or pg_catalog.length(p_reason) > 500
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
    or p_event_date is null
    or extract(year from p_event_date)::integer <> p_income_year
    or pg_catalog.jsonb_typeof(p_correction_source) is distinct from 'object'
    or p_correction_source ->> 'role' <> 'CORROBORATING'
    or p_correction_source ->> 'capability' <> 'DOCUMENTS'
    or pg_catalog.btrim(coalesce(p_correction_source ->> 'recordId', '')) = ''
    or coalesce(p_correction_source ->> 'revision', '') !~ '^[1-9][0-9]*$'
    or coalesce(p_correction_source ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  v_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'originalEntryId', p_original_entry_id,
      'reason', pg_catalog.btrim(p_reason),
      'correlationId', pg_catalog.btrim(p_correlation_id),
      'eventDate', p_event_date,
      'correctionSource', p_correction_source
    )::text,
    'sha256'
  ), 'hex');

  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':reverse_supported_entry:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'reverse_supported_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'original_entry_id')::uuid,
      (v_receipt.result ->> 'reversal_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      (v_receipt.result ->> 'reversed_at')::timestamptz,
      true;
    return;
  end if;

  if p_income_year is distinct from extract(year from current_date)::integer then
    raise exception 'ledger_prior_year_correction_policy_unresolved';
  end if;
  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  select entry.* into v_original
  from ledger.entries entry
  where entry.id = p_original_entry_id
    and entry.company_id = p_company_id
    and entry.income_year = p_income_year;
  if not found then
    raise exception 'ledger_not_found';
  end if;
  if v_original.entry_kind not in (
    'CAPITAL_INCREASE', 'CAPITAL_REDUCTION', 'SHAREHOLDER_LOAN',
    'INTERCOMPANY_LOAN', 'BANK_LOAN', 'GROUP_CONTRIBUTION'
  ) then
    raise exception 'ledger_correction_original_kind_unsupported';
  end if;
  if exists (
    select 1 from ledger.entry_reversals reversal
    where reversal.original_entry_id = p_original_entry_id
  ) or exists (
    select 1 from ledger.entry_corrections correction
    where correction.original_entry_id = p_original_entry_id
  ) then
    raise exception 'ledger_entry_already_corrected';
  end if;

  select pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'account', line ->> 'account',
      'description', line ->> 'description',
      'debit', pg_catalog.round((line ->> 'credit')::numeric, 2),
      'credit', pg_catalog.round((line ->> 'debit')::numeric, 2),
      'currency', 'NOK'
    ) order by ordinal
  ) into v_lines
  from pg_catalog.jsonb_array_elements(v_original.lines)
    with ordinality item(line, ordinal);

  v_reversal_id := pg_catalog.gen_random_uuid();
  v_reversed_at := pg_catalog.statement_timestamp();
  v_original_digest := pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(v_original)::text, 'sha256'), 'hex'
  );
  v_sources := pg_catalog.jsonb_build_array(
    pg_catalog.jsonb_build_object(
      'role', 'PRIMARY', 'capability', 'LEDGER',
      'recordId', p_original_entry_id::text, 'revision', 1,
      'factSha256', v_original_digest
    ),
    p_correction_source
  );
  v_sources_digest := pg_catalog.encode(
    extensions.digest(v_sources::text, 'sha256'), 'hex'
  );

  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    v_reversal_id, p_company_id, p_income_year, 'CORRECTION_REVERSAL',
    'Full reversal: ' || pg_catalog.btrim(p_reason), v_lines, '[]'::jsonb,
    null, null, v_reversed_at, v_actor_id, v_reversed_at,
    'LEDGER', 'supported-event-reversal:' || p_original_entry_id::text,
    pg_catalog.btrim(p_correlation_id)
  );
  insert into ledger.entry_contexts (
    entry_id, company_id, income_year, event_date, rule_version,
    sources_digest, recorded_at
  ) values (
    v_reversal_id, p_company_id, p_income_year, p_event_date,
    'ledger-supported-patterns-2026.1', v_sources_digest, v_reversed_at
  );
  insert into ledger.entry_sources (
    entry_id, company_id, income_year, ordinal, source_role,
    source_capability, source_record_id, source_revision, fact_sha256
  ) values (
    v_reversal_id, p_company_id, p_income_year, 1, 'PRIMARY', 'LEDGER',
    p_original_entry_id::text, 1, v_original_digest
  );
  insert into ledger.entry_sources (
    entry_id, company_id, income_year, ordinal, source_role,
    source_capability, source_record_id, source_revision, fact_sha256
  ) values (
    v_reversal_id, p_company_id, p_income_year, 2, 'CORROBORATING', 'DOCUMENTS',
    p_correction_source ->> 'recordId',
    (p_correction_source ->> 'revision')::integer,
    p_correction_source ->> 'factSha256'
  );
  insert into ledger.entry_reversals (
    original_entry_id, reversal_entry_id, company_id, income_year,
    reason, reversed_by, reversed_at
  ) values (
    p_original_entry_id, v_reversal_id, p_company_id, p_income_year,
    pg_catalog.btrim(p_reason), v_actor_id, v_reversed_at
  );

  v_result := pg_catalog.jsonb_build_object(
    'original_entry_id', p_original_entry_id,
    'reversal_entry_id', v_reversal_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'reversed_at', v_reversed_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result, completed_at
  ) values (
    'v1', v_actor_id, p_company_id, 'reverse_supported_entry',
    p_idempotency_key, v_fingerprint, v_result, v_reversed_at
  );

  return query select p_original_entry_id, v_reversal_id, p_company_id,
    p_income_year, v_reversed_at, false;
end;
$function$;

revoke all on ledger.entry_reversals
from public, anon, authenticated, ledger_executor;
grant select, insert on ledger.entry_reversals to ledger_store_owner;
revoke all on function ledger.reverse_supported_entry_v1(
  text, uuid, integer, uuid, text, text, text, date, jsonb
) from public, anon, authenticated;
grant execute on function ledger.reverse_supported_entry_v1(
  text, uuid, integer, uuid, text, text, text, date, jsonb
) to ledger_executor;
alter function ledger.reverse_supported_entry_v1(
  text, uuid, integer, uuid, text, text, text, date, jsonb
) owner to ledger_store_owner;

reset role;

do $authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$authority_revoke$;

commit;
