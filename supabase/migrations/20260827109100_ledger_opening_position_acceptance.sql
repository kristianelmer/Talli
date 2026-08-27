-- Issue #188 opening-position acceptance upgrade.
--
-- Migration 090 can already exist on a predecessor database. Replacing the
-- historical 020 source text is not sufficient to remove that database's
-- source-count constraint, admit annual-accounts evidence, or refresh the
-- private supported-entry storage coordinator. Apply those changes additively.

begin;

do $ledger_opening_acceptance_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
end
$ledger_opening_acceptance_authority$;

alter table ledger.entry_sources
  drop constraint if exists entry_sources_ordinal_check;
alter table ledger.entry_sources
  add constraint entry_sources_ordinal_check check (ordinal >= 1);

alter table ledger.entry_sources
  drop constraint if exists entry_sources_source_capability_check;
alter table ledger.entry_sources
  add constraint entry_sources_source_capability_check check (
    source_capability in (
      'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
      'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING',
      'ANNUAL_ACCOUNTS_FILING', 'DOCUMENTS'
    )
  );

create or replace function ledger.post_supported_entry_storage_v1(
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
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_has_receipt boolean;
begin
  if p_event_date is null
    or extract(year from p_event_date)::integer <> p_income_year
    or coalesce(p_rule_version, '')
      !~ '^ledger-supported-patterns-[0-9]{4}[.][0-9]+$'
    or pg_catalog.jsonb_typeof(p_sources) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_sources) < 1
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' is distinct from p_source_capability
    or p_sources -> 0 ->> 'recordId' is distinct from p_source_record_id
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources)
        with ordinality source(item, ordinal)
      where item ->> 'role' is distinct from case
          when ordinal = 1 then 'PRIMARY' else 'CORROBORATING'
        end
        or item ->> 'capability' not in (
          'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
          'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING',
          'ANNUAL_ACCOUNTS_FILING', 'DOCUMENTS'
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
  if pg_catalog.upper(p_entry_kind) = 'OPENING_BALANCE' then
    if v_actor_id is not null
      and p_verified_subject ~ '^[0-9a-fA-F-]{36}$'
      and v_actor_id is not distinct from p_verified_subject::uuid
      and p_company_id is not null
      and p_income_year between 2000 and 2100
      and coalesce(p_idempotency_key, '') ~ '^[A-Za-z0-9._:-]{16,255}$'
    then
      select exists (
        select 1
        from backend_system.ledger_command_receipts receipt
        where receipt.api_major = 'v1'
          and receipt.actor_id = v_actor_id
          and receipt.company_id = p_company_id
          and receipt.operation_name = 'post_entry'
          and receipt.idempotency_key = p_idempotency_key
      ) into v_has_receipt;

      if not v_has_receipt then
        perform ledger.lock_company_year_v1(p_company_id, p_income_year);

        select exists (
          select 1
          from backend_system.ledger_command_receipts receipt
          where receipt.api_major = 'v1'
            and receipt.actor_id = v_actor_id
            and receipt.company_id = p_company_id
            and receipt.operation_name = 'post_entry'
            and receipt.idempotency_key = p_idempotency_key
        ) into v_has_receipt;

        if not v_has_receipt and exists (
          select 1
          from ledger.company_year_close_locks close_lock
          where close_lock.company_id = p_company_id
            and close_lock.income_year = p_income_year
        ) then
          raise exception 'ledger_period_locked';
        end if;
      end if;
    end if;

    select * into strict v_post
    from ledger.post_entry_without_company_year_close_lock_v1(
      p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
      p_lines, '[]'::jsonb, false, p_source_capability, p_source_record_id,
      p_correlation_id, p_verified_subject
    );
  else
    select * into strict v_post
    from ledger.post_entry(
      p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
      p_lines, '[]'::jsonb, false, p_source_capability, p_source_record_id,
      p_correlation_id, p_verified_subject
    );
  end if;

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
      entry_id, company_id, income_year, event_date, rule_version,
      sources_digest
    ) values (
      v_post.ledger_entry_id, p_company_id, p_income_year, p_event_date,
      p_rule_version, v_sources_digest
    );
    insert into ledger.entry_sources (
      entry_id, company_id, income_year, ordinal, source_role,
      source_capability, source_record_id, source_revision, fact_sha256
    )
    select v_post.ledger_entry_id, p_company_id, p_income_year,
      ordinal::integer, item ->> 'role', item ->> 'capability',
      item ->> 'recordId', (item ->> 'revision')::integer,
      item ->> 'factSha256'
    from pg_catalog.jsonb_array_elements(p_sources)
      with ordinality source(item, ordinal);
  end if;

  return query select v_post.ledger_entry_id, v_post.company_id,
    v_post.income_year, v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

revoke all on function ledger.post_supported_entry_storage_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;
alter function ledger.post_supported_entry_storage_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;

do $ledger_opening_acceptance_authority_revoke$
begin
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_opening_acceptance_authority_revoke$;

commit;
