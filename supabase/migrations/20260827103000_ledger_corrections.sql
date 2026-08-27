-- Issue #188: immutable full-reversal correction followed by a typed replacement.
-- Accounting selection remains in the ledger module; this coordinator only
-- reverses stored lines and persists the already-approved replacement.

alter table backend_system.ledger_command_receipts
  drop constraint if exists ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check check (
    operation_name in (
      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',
      'close_company_year'
    )
  );

create unique index if not exists ledger_entries_id_company_year_uidx
  on ledger.entries(id, company_id, income_year);

create table if not exists ledger.entry_corrections (
  original_entry_id uuid primary key,
  reversal_entry_id uuid not null unique,
  replacement_entry_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  reason text not null check (
    pg_catalog.btrim(reason) <> '' and pg_catalog.length(reason) <= 500
  ),
  corrected_by uuid not null references auth.users(id) on delete restrict,
  corrected_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (original_entry_id, company_id, income_year),
  foreign key (original_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  foreign key (reversal_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  foreign key (replacement_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (original_entry_id <> reversal_entry_id),
  check (original_entry_id <> replacement_entry_id),
  check (reversal_entry_id <> replacement_entry_id)
);

create index if not exists ledger_entry_corrections_company_year_idx
  on ledger.entry_corrections(company_id, income_year, corrected_at, original_entry_id);

alter table ledger.entry_corrections enable row level security;
alter table ledger.entry_corrections force row level security;

drop policy if exists "ledger store reads entry corrections"
  on ledger.entry_corrections;
create policy "ledger store reads entry corrections"
on ledger.entry_corrections for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records entry corrections"
  on ledger.entry_corrections;
create policy "ledger store records entry corrections"
on ledger.entry_corrections for insert to ledger_store_owner
with check (
  corrected_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

-- The physical storage invariant recognizes reversal rows. The public posting
-- function deliberately remains closed and cannot create this technical kind.
create or replace function ledger.enforce_entry_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  new.entry_kind := case pg_catalog.lower(pg_catalog.btrim(new.entry_kind))
    when 'opening_balance' then 'OPENING_BALANCE'
    when 'admin_cost' then 'ADMINISTRATIVE_COST'
    when 'administrative_cost' then 'ADMINISTRATIVE_COST'
    when 'manual_journal' then 'MANUAL_JOURNAL'
    when 'bank_rule_suggestion' then 'BANK_RULE_SUGGESTION'
    when 'dividend_received' then 'DIVIDEND_RECEIVED'
    when 'dividend_to_owner_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'owner_dividend_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'dividend_to_owner_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'owner_dividend_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'share_purchase' then 'SHARE_PURCHASE'
    when 'share_sale' then 'SHARE_SALE'
    when 'shareholder_loan' then 'SHAREHOLDER_LOAN'
    when 'tax_settlement' then 'TAX_SETTLEMENT'
    when 'correction_reversal' then 'CORRECTION_REVERSAL'
    else pg_catalog.upper(pg_catalog.btrim(new.entry_kind))
  end;
  if new.entry_kind not in (
    'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
    'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
    'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
    'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
    'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
    'CAPITAL_REDUCTION', 'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION',
    'INTERCOMPANY_LOAN', 'CORRECTION_REVERSAL'
  ) or not ledger.entry_lines_are_valid_v1(new.lines, true) then
    raise exception 'ledger_invalid_input';
  end if;
  new.lines := ledger.normalize_lines_v1(new.lines);
  new.source_capability := coalesce(
    new.source_capability,
    case new.entry_kind
      when 'OPENING_BALANCE' then case
        when nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
        then 'SHAREHOLDER_REGISTER_FILING'
        else 'LEDGER'
      end
      when 'BANK_RULE_SUGGESTION' then 'BANKING'
      when 'DIVIDEND_RECEIVED' then 'INVESTMENTS'
      when 'SHARE_PURCHASE' then 'INVESTMENTS'
      when 'SHARE_SALE' then 'INVESTMENTS'
      when 'OWNER_DIVIDEND_DECLARED' then 'CORPORATE_GOVERNANCE'
      when 'OWNER_DIVIDEND_PAYMENT' then 'CORPORATE_GOVERNANCE'
      when 'SHAREHOLDER_LOAN' then 'CORPORATE_GOVERNANCE'
      when 'TAX_SETTLEMENT' then 'COMPANY_TAX_FILING'
      when 'BANK_INTEREST' then 'BANKING'
      when 'BANK_LOAN' then 'BANKING'
      when 'CAPITAL_INCREASE' then 'CORPORATE_GOVERNANCE'
      when 'CAPITAL_REDUCTION' then 'CORPORATE_GOVERNANCE'
      when 'COMPANY_TAX_ACCRUAL' then 'COMPANY_TAX_FILING'
      when 'GROUP_CONTRIBUTION' then 'CORPORATE_GOVERNANCE'
      when 'INTERCOMPANY_LOAN' then 'CORPORATE_GOVERNANCE'
      else 'LEDGER'
    end
  );
  new.source_record_id := coalesce(
    nullif(pg_catalog.btrim(new.source_record_id), ''),
    case
      when new.entry_kind = 'OPENING_BALANCE'
        and nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
      then 'opening-setup:' || (pg_catalog.to_jsonb(new) ->> 'setup_id')
      else 'rollback:' || new.id::text
    end
  );
  new.correlation_id := coalesce(
    nullif(pg_catalog.btrim(new.correlation_id), ''),
    'rollback:' || new.id::text
  );
  return new;
end;
$function$;

create or replace function ledger.correct_entry_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_original_entry_id uuid,
  p_reason text,
  p_replacement_kind text,
  p_replacement_memo text,
  p_replacement_lines jsonb,
  p_correlation_id text,
  p_verified_subject text,
  p_event_date date,
  p_correction_scope text,
  p_rule_version text,
  p_sources jsonb
)
returns table (
  reversal_entry_id uuid,
  replacement_entry_id uuid,
  company_id uuid,
  income_year integer,
  corrected_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_original record;
  v_reversal_entry_id uuid;
  v_replacement_entry_id uuid;
  v_corrected_at timestamptz;
  v_reversal_lines jsonb;
  v_original_digest text;
  v_reversal_sources jsonb;
  v_reversal_sources_digest text;
  v_replacement_sources_digest text;
  v_computed_fingerprint text;
  v_result jsonb;
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_correction_scope = 'PRIOR_YEAR_ERROR' then
    raise exception 'ledger_prior_year_correction_policy_unresolved';
  end if;
  if p_company_id is null
    or p_original_entry_id is null
    or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or pg_catalog.length(p_reason) > 500
    or pg_catalog.btrim(coalesce(p_replacement_memo, '')) = ''
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
    or p_event_date is null
    or extract(year from p_event_date)::integer <> p_income_year
    or p_correction_scope is distinct from 'CURRENT_COMPANY_YEAR'
    or coalesce(p_rule_version, '') !~ '^ledger-supported-patterns-[0-9]{4}\.[0-9]+$'
    or pg_catalog.upper(coalesce(p_replacement_kind, '')) not in (
      'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL', 'BANK_RULE_SUGGESTION',
      'DIVIDEND_RECEIVED', 'OWNER_DIVIDEND_DECLARED',
      'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE', 'SHARE_SALE',
      'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT', 'BANK_INTEREST', 'BANK_LOAN',
      'CAPITAL_INCREASE', 'CAPITAL_REDUCTION', 'COMPANY_TAX_ACCRUAL',
      'GROUP_CONTRIBUTION', 'INTERCOMPANY_LOAN'
    )
    or not ledger.entry_lines_are_valid_v1(p_replacement_lines, false)
    or pg_catalog.jsonb_typeof(p_sources) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_sources) not between 2 and 100
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' <> 'DOCUMENTS'
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources) with ordinality source(item, ordinal)
      where item ->> 'role' is distinct from case
          when ordinal = 1 then 'PRIMARY' else 'CORROBORATING'
        end
        or item ->> 'capability' is distinct from case
          when ordinal = 1 then 'DOCUMENTS' else 'BANKING'
        end
        or pg_catalog.btrim(coalesce(item ->> 'recordId', '')) = ''
        or pg_catalog.length(item ->> 'recordId') > 255
        or coalesce(item ->> 'revision', '') !~ '^[1-9][0-9]*$'
        or coalesce(item ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
    )
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources) source(item)
      group by item ->> 'capability', item ->> 'recordId', item ->> 'revision'
      having pg_catalog.count(*) > 1
    )
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
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'originalEntryId', p_original_entry_id,
      'reason', pg_catalog.btrim(p_reason),
      'replacementKind', pg_catalog.upper(p_replacement_kind),
      'replacementMemo', pg_catalog.btrim(p_replacement_memo),
      'replacementLines', ledger.normalize_lines_v1(p_replacement_lines),
      'correlationId', pg_catalog.btrim(p_correlation_id),
      'eventDate', p_event_date,
      'correctionScope', p_correction_scope,
      'ruleVersion', p_rule_version,
      'sources', p_sources
    )::text,
    'sha256'
  ), 'hex');

  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':correct_entry:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'correct_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'reversal_entry_id')::uuid,
      (v_receipt.result ->> 'replacement_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      (v_receipt.result ->> 'corrected_at')::timestamptz,
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
  if v_original.entry_kind <> 'ADMINISTRATIVE_COST' then
    raise exception 'ledger_correction_original_kind_unsupported';
  end if;
  if v_original.entry_kind = 'CORRECTION_REVERSAL'
    or exists (
      select 1 from ledger.entry_corrections correction
      where correction.original_entry_id = p_original_entry_id
    )
  then
    raise exception 'ledger_entry_already_corrected';
  end if;

  select pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'account', line ->> 'account',
      'description', line ->> 'description',
      'debit', round((line ->> 'credit')::numeric, 2),
      'credit', round((line ->> 'debit')::numeric, 2),
      'currency', 'NOK'
    ) order by ordinal
  ) into v_reversal_lines
  from pg_catalog.jsonb_array_elements(v_original.lines)
    with ordinality item(line, ordinal);

  v_reversal_entry_id := pg_catalog.gen_random_uuid();
  v_replacement_entry_id := pg_catalog.gen_random_uuid();
  v_corrected_at := pg_catalog.statement_timestamp();
  v_original_digest := pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(v_original)::text, 'sha256'), 'hex'
  );
  v_reversal_sources := pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
    'role', 'PRIMARY',
    'capability', 'LEDGER',
    'recordId', p_original_entry_id::text,
    'revision', 1,
    'factSha256', v_original_digest
  ));
  v_reversal_sources_digest := pg_catalog.encode(
    extensions.digest(v_reversal_sources::text, 'sha256'), 'hex'
  );
  v_replacement_sources_digest := pg_catalog.encode(
    extensions.digest(p_sources::text, 'sha256'), 'hex'
  );

  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values
  (
    v_reversal_entry_id, p_company_id, p_income_year, 'CORRECTION_REVERSAL',
    'Full reversal: ' || pg_catalog.btrim(p_reason), v_reversal_lines,
    '[]'::jsonb, null, null, v_corrected_at, v_actor_id, v_corrected_at,
    'LEDGER', 'correction-reversal:' || p_original_entry_id::text,
    pg_catalog.btrim(p_correlation_id)
  ),
  (
    v_replacement_entry_id, p_company_id, p_income_year,
    pg_catalog.upper(p_replacement_kind), pg_catalog.btrim(p_replacement_memo),
    ledger.normalize_lines_v1(p_replacement_lines), '[]'::jsonb,
    null, null, v_corrected_at, v_actor_id, v_corrected_at,
    'DOCUMENTS', pg_catalog.btrim(p_sources -> 0 ->> 'recordId'),
    pg_catalog.btrim(p_correlation_id)
  );

  insert into ledger.entry_contexts (
    entry_id, company_id, income_year, event_date, rule_version, sources_digest,
    recorded_at
  ) values
  (
    v_reversal_entry_id, p_company_id, p_income_year, p_event_date,
    p_rule_version, v_reversal_sources_digest, v_corrected_at
  ),
  (
    v_replacement_entry_id, p_company_id, p_income_year, p_event_date,
    p_rule_version, v_replacement_sources_digest, v_corrected_at
  );

  insert into ledger.entry_sources (
    entry_id, company_id, income_year, ordinal, source_role,
    source_capability, source_record_id, source_revision, fact_sha256
  ) values (
    v_reversal_entry_id, p_company_id, p_income_year, 1, 'PRIMARY', 'LEDGER',
    p_original_entry_id::text, 1, v_original_digest
  );
  insert into ledger.entry_sources (
    entry_id, company_id, income_year, ordinal, source_role,
    source_capability, source_record_id, source_revision, fact_sha256
  )
  select
    v_replacement_entry_id, p_company_id, p_income_year, ordinal::integer,
    item ->> 'role', item ->> 'capability', item ->> 'recordId',
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_sources)
    with ordinality source(item, ordinal);

  insert into ledger.entry_corrections (
    original_entry_id, reversal_entry_id, replacement_entry_id,
    company_id, income_year, reason, corrected_by, corrected_at
  ) values (
    p_original_entry_id, v_reversal_entry_id, v_replacement_entry_id,
    p_company_id, p_income_year, pg_catalog.btrim(p_reason), v_actor_id,
    v_corrected_at
  );

  v_result := pg_catalog.jsonb_build_object(
    'reversal_entry_id', v_reversal_entry_id,
    'replacement_entry_id', v_replacement_entry_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'corrected_at', v_corrected_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result, completed_at
  ) values (
    'v1', v_actor_id, p_company_id, 'correct_entry', p_idempotency_key,
    v_computed_fingerprint, v_result, v_corrected_at
  );

  return query select
    v_reversal_entry_id, v_replacement_entry_id, p_company_id, p_income_year,
    v_corrected_at, false;
end;
$function$;

revoke all on ledger.entry_corrections
from public, anon, authenticated, ledger_executor;
grant select, insert on ledger.entry_corrections to ledger_store_owner;

revoke all on function ledger.correct_entry_v1(
  text, uuid, integer, uuid, text, text, text, jsonb, text, text,
  date, text, text, jsonb
) from public, anon, authenticated;
grant execute on function ledger.correct_entry_v1(
  text, uuid, integer, uuid, text, text, text, jsonb, text, text,
  date, text, text, jsonb
) to ledger_executor;

do $ledger_correction_ownership_membership$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
end
$ledger_correction_ownership_membership$;

alter table ledger.entry_corrections owner to ledger_store_owner;
alter function ledger.correct_entry_v1(
  text, uuid, integer, uuid, text, text, text, jsonb, text, text,
  date, text, text, jsonb
) owner to ledger_store_owner;

do $ledger_correction_ownership_membership_revoke$
begin
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_correction_ownership_membership_revoke$;

drop trigger if exists ledger_entry_corrections_immutable
  on ledger.entry_corrections;
create trigger ledger_entry_corrections_immutable
before update or delete on ledger.entry_corrections
for each row execute function backend_system.prevent_ledger_technical_mutation();
