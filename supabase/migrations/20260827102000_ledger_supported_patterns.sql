-- Issue #188 expand: immutable source provenance for supported holding actions.
-- Accounting translation remains exclusively in the Python ledger module.

create table if not exists ledger.entry_contexts (
  entry_id uuid primary key references ledger.entries(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  event_date date not null,
  rule_version text not null check (
    rule_version ~ '^ledger-supported-patterns-[0-9]{4}\.[0-9]+$'
  ),
  sources_digest text not null check (sources_digest ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (entry_id, company_id, income_year),
  check (extract(year from event_date)::integer = income_year)
);

create table if not exists ledger.entry_sources (
  entry_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 100),
  source_role text not null check (source_role in ('PRIMARY', 'CORROBORATING')),
  source_capability text not null check (source_capability in (
    'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
    'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING', 'DOCUMENTS'
  )),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  source_revision integer not null check (source_revision >= 1),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  primary key (entry_id, ordinal),
  unique (entry_id, source_capability, source_record_id, source_revision),
  foreign key (entry_id, company_id, income_year)
    references ledger.entry_contexts(entry_id, company_id, income_year)
    on delete restrict
);

create unique index if not exists ledger_entry_sources_one_primary_uidx
  on ledger.entry_sources(entry_id)
  where source_role = 'PRIMARY';

alter table ledger.entry_contexts enable row level security;
alter table ledger.entry_contexts force row level security;
alter table ledger.entry_sources enable row level security;
alter table ledger.entry_sources force row level security;

drop policy if exists "ledger store reads entry contexts" on ledger.entry_contexts;
create policy "ledger store reads entry contexts"
on ledger.entry_contexts for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records entry contexts" on ledger.entry_contexts;
create policy "ledger store records entry contexts"
on ledger.entry_contexts for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "ledger store reads entry sources" on ledger.entry_sources;
create policy "ledger store reads entry sources"
on ledger.entry_sources for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records entry sources" on ledger.entry_sources;
create policy "ledger store records entry sources"
on ledger.entry_sources for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

-- This replaces the canonical writer at the active ledger stage. It changes
-- only the closed entry-kind set; balance, authorization, locking, receipts,
-- and idempotency remain the #139-proven implementation.
create or replace function ledger.post_entry(
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
  p_verified_subject text
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
  v_entry_id uuid;
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
  if p_company_id is null or p_income_year not between 2000 and 2100
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
      'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
      'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
      'CAPITAL_REDUCTION', 'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION',
      'INTERCOMPANY_LOAN'
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
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'entryKind', pg_catalog.upper(p_entry_kind),
      'memo', pg_catalog.btrim(p_memo),
      'lines', ledger.normalize_lines_v1(p_lines),
      'riskFlags', p_risk_flags,
      'warningAccepted', p_warning_accepted,
      'sourceCapability', p_source_capability,
      'sourceRecordId', pg_catalog.btrim(p_source_record_id)
    )::text,
    'sha256'
  ), 'hex');
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':post_entry:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'post_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'ledger_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      v_receipt.result ->> 'entry_kind',
      (v_receipt.result ->> 'posted_at')::timestamptz,
      true;
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
    where entry.company_id = p_company_id
      and entry.source_capability = p_source_capability
      and entry.source_record_id = p_source_record_id
  ) then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if pg_catalog.upper(p_entry_kind) = 'OPENING_BALANCE' and exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and entry.entry_kind = 'OPENING_BALANCE'
  ) then
    raise exception 'ledger_opening_already_exists';
  end if;

  v_entry_id := pg_catalog.gen_random_uuid();
  v_posted_at := pg_catalog.statement_timestamp();
  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    pg_catalog.btrim(p_memo), ledger.normalize_lines_v1(p_lines),
    p_risk_flags,
    case when p_warning_accepted then v_actor_id else null end,
    case when p_warning_accepted then v_posted_at else null end,
    v_posted_at, v_actor_id, v_posted_at,
    p_source_capability, pg_catalog.btrim(p_source_record_id),
    pg_catalog.btrim(p_correlation_id)
  );

  v_result := pg_catalog.jsonb_build_object(
    'ledger_entry_id', v_entry_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'entry_kind', pg_catalog.upper(p_entry_kind),
    'posted_at', v_posted_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'post_entry', p_idempotency_key,
    v_computed_fingerprint, v_result
  );

  return query select
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    v_posted_at, false;
end;
$function$;

create or replace function ledger.post_supported_entry_v1(
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
  p_event_date date,
  p_rule_version text,
  p_sources jsonb
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
  v_post record;
  v_sources_digest text;
begin
  if p_event_date is null
    or extract(year from p_event_date)::integer <> p_income_year
    or coalesce(p_rule_version, '') !~ '^ledger-supported-patterns-[0-9]{4}\.[0-9]+$'
    or pg_catalog.jsonb_typeof(p_sources) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_sources) not between 1 and 100
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' is distinct from p_source_capability
    or p_sources -> 0 ->> 'recordId' is distinct from p_source_record_id
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources) with ordinality source(item, ordinal)
      where item ->> 'role' is distinct from case
          when ordinal = 1 then 'PRIMARY' else 'CORROBORATING'
        end
        or item ->> 'capability' not in (
          'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
          'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING'
        )
        or pg_catalog.btrim(coalesce(item ->> 'recordId', '')) = ''
        or pg_catalog.length(item ->> 'recordId') > 255
        or coalesce(item ->> 'revision', '') !~ '^[1-9][0-9]*$'
        or coalesce(item ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
    )
  then
    raise exception 'ledger_invalid_input';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_sources) source(item)
    group by item ->> 'capability', item ->> 'recordId', item ->> 'revision'
    having pg_catalog.count(*) > 1
  ) then
    raise exception 'ledger_invalid_input';
  end if;

  v_sources_digest := pg_catalog.encode(
    extensions.digest(p_sources::text, 'sha256'), 'hex'
  );
  select * into strict v_post
  from ledger.post_entry(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, '[]'::jsonb, false, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject
  );

  if v_post.replayed then
    if not exists (
      select 1 from ledger.entry_contexts context
      where context.entry_id = v_post.ledger_entry_id
        and context.company_id = p_company_id
        and context.income_year = p_income_year
        and context.event_date = p_event_date
        and context.rule_version = p_rule_version
        and context.sources_digest = v_sources_digest
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    insert into ledger.entry_contexts (
      entry_id, company_id, income_year, event_date, rule_version, sources_digest
    ) values (
      v_post.ledger_entry_id, p_company_id, p_income_year, p_event_date,
      p_rule_version, v_sources_digest
    );
    insert into ledger.entry_sources (
      entry_id, company_id, income_year, ordinal, source_role,
      source_capability, source_record_id, source_revision, fact_sha256
    )
    select
      v_post.ledger_entry_id, p_company_id, p_income_year, ordinal::integer,
      item ->> 'role', item ->> 'capability', item ->> 'recordId',
      (item ->> 'revision')::integer, item ->> 'factSha256'
    from pg_catalog.jsonb_array_elements(p_sources)
      with ordinality source(item, ordinal);
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

-- The physical insert trigger remains a generic storage invariant and accepts
-- the expanded closed kind set without selecting any accounting route.
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

revoke all on ledger.entry_contexts, ledger.entry_sources
from public, anon, authenticated, ledger_executor;
grant select, insert on ledger.entry_contexts, ledger.entry_sources
to ledger_store_owner;

revoke all on function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated;
grant execute on function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) to ledger_executor;

alter table ledger.entry_contexts owner to ledger_store_owner;
alter table ledger.entry_sources owner to ledger_store_owner;
alter function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;

drop trigger if exists ledger_entry_contexts_immutable on ledger.entry_contexts;
create trigger ledger_entry_contexts_immutable
before update or delete on ledger.entry_contexts
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_entry_sources_immutable on ledger.entry_sources;
create trigger ledger_entry_sources_immutable
before update or delete on ledger.entry_sources
for each row execute function backend_system.prevent_ledger_technical_mutation();
