-- Remove the executable year-end workflow only before it has recorded data.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant investments_store_owner to %I', current_user);
end
$authority$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:year-end-measurement:v2', 0)
);

do $guard$
begin
  if exists (
    select 1 from investments.year_end_measurements
    where idempotency_key is not null
  ) or exists (
    select 1 from ledger.entries
    where entry_kind = 'INVESTMENT_MEASUREMENT'
  ) then
    raise exception 'investments_year_end_measurement_rollback_unsafe';
  end if;
end
$guard$;

revoke all on function
  investments.get_year_end_measurement_replay_v2(jsonb, text),
  investments.prepare_year_end_measurement_v2(jsonb, text),
  investments.complete_year_end_measurement_v2(jsonb, uuid, jsonb, text)
from investments_workflow_executor;

set local role investments_store_owner;
drop function investments.complete_year_end_measurement_v2(
  jsonb, uuid, jsonb, text
);
drop function investments.prepare_year_end_measurement_v2(jsonb, text);
drop function investments.get_year_end_measurement_replay_v2(jsonb, text);
drop function investments.year_end_measurement_fingerprint_v2(jsonb);
alter table investments.year_end_measurements
  drop constraint year_end_measurements_actor_idempotency_unique,
  drop constraint year_end_measurements_evidence_authority_check,
  drop constraint year_end_measurements_evidence_reference_check,
  drop constraint year_end_measurements_evidence_mode_check,
  drop constraint year_end_measurements_request_fingerprint_check,
  drop constraint year_end_measurements_idempotency_key_check,
  drop column owner_attested,
  drop column evidence_reference,
  drop column evidence_mode,
  drop column request_fingerprint,
  drop column idempotency_key;
reset role;

-- Restore the predecessor investment receiver's closed kind set.
create or replace function ledger.post_investment_lifecycle_entry_v2(
  p_idempotency_key text, p_company_id uuid, p_income_year integer,
  p_entry_kind text, p_memo text, p_lines jsonb,
  p_source_capability text, p_source_record_id text,
  p_correlation_id text, p_verified_subject text, p_event_date date,
  p_rule_version text, p_sources jsonb
)
returns table (
  ledger_entry_id uuid, company_id uuid, income_year integer,
  entry_kind text, posted_at timestamptz, replayed boolean
)
language plpgsql security definer set search_path = ''
as $function$
declare v_corroborating_capability text;
begin
  if p_source_capability <> 'INVESTMENTS'
    or p_entry_kind not in (
      'SHARE_PURCHASE', 'SHARE_SALE', 'DIVIDEND_RECEIVED'
    )
    or p_rule_version <> 'ledger-supported-patterns-2026.1'
    or pg_catalog.jsonb_typeof(p_sources) <> 'array'
    or pg_catalog.jsonb_array_length(p_sources) < 2
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' <> 'INVESTMENTS'
    or p_sources -> 0 ->> 'recordId' <> p_source_record_id
    or exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources)
        with ordinality source(item, ordinal)
      where ordinal > 1 and item ->> 'role' <> 'CORROBORATING'
    )
  then raise exception 'ledger_invalid_input'; end if;
  select p_sources -> 1 ->> 'capability' into v_corroborating_capability;
  if v_corroborating_capability not in ('BANKING', 'DOCUMENTS')
    or exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources)
        with ordinality source(item, ordinal)
      where ordinal > 1
        and item ->> 'capability' <> v_corroborating_capability
    )
  then raise exception 'ledger_source_capability_mismatch'; end if;
  if (v_corroborating_capability = 'BANKING'
      and pg_catalog.jsonb_array_length(p_sources) <> 2)
    or (v_corroborating_capability = 'DOCUMENTS'
      and pg_catalog.jsonb_array_length(p_sources) not between 2 and 51)
  then raise exception 'ledger_source_capability_mismatch'; end if;
  return query select * from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, p_source_capability, p_source_record_id, p_correlation_id,
    p_verified_subject, p_event_date, p_rule_version, p_sources
  );
end;
$function$;

-- Restore the exact predecessor storage invariant. The underlying generic
-- writer may still parse the removed token, but this trigger and the restricted
-- investment receiver both reject it before any row or receipt can commit.
create or replace function ledger.enforce_entry_v1()
returns trigger language plpgsql security definer set search_path = ''
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

alter function ledger.post_investment_lifecycle_entry_v2(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.enforce_entry_v1() owner to ledger_store_owner;

do $authority_revoke$
begin
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
  execute pg_catalog.format('revoke investments_store_owner from %I', current_user);
end
$authority_revoke$;

commit;
