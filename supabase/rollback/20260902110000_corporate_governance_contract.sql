-- Restore a read-only predecessor projection and fail closed canonical writers.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.set_config(
  'talli.corporate_governance_contract_rollback_principal', current_user, true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, '
      || 'company_archive_projection_executor to %I', current_user
  );
end
$membership$;

-- Rollback intentionally exposes only a read-only predecessor projection.
-- Preserve the exact canonical definitions, then make every finalization and
-- payment entry point fail before it can create documents, ledger entries, or
-- payment evidence.
set local role corporate_governance_store_owner;
do $preserve_contract_writers$
declare
  routine record;
  v_definition text;
begin
  for routine in select * from (values
    (
      'corporate_governance.prepare_owner_dividend_finalization_v1(jsonb,text)',
      'corporate_governance.prepare_owner_dividend_finalization_contract_v1(jsonb,text)',
      'FUNCTION corporate_governance.prepare_owner_dividend_finalization_v1',
      'FUNCTION corporate_governance.prepare_owner_dividend_finalization_contract_v1'
    ),
    (
      'corporate_governance.complete_owner_dividend_finalization_v1(jsonb,text)',
      'corporate_governance.complete_owner_dividend_finalization_contract_v1(jsonb,text)',
      'FUNCTION corporate_governance.complete_owner_dividend_finalization_v1',
      'FUNCTION corporate_governance.complete_owner_dividend_finalization_contract_v1'
    ),
    (
      'corporate_governance.prepare_owner_dividend_payment_v1(jsonb,text)',
      'corporate_governance.prepare_owner_dividend_payment_contract_v1(jsonb,text)',
      'FUNCTION corporate_governance.prepare_owner_dividend_payment_v1',
      'FUNCTION corporate_governance.prepare_owner_dividend_payment_contract_v1'
    ),
    (
      'corporate_governance.complete_owner_dividend_payment_v1(jsonb,text)',
      'corporate_governance.complete_owner_dividend_payment_contract_v1(jsonb,text)',
      'FUNCTION corporate_governance.complete_owner_dividend_payment_v1',
      'FUNCTION corporate_governance.complete_owner_dividend_payment_contract_v1'
    ),
    (
      'corporate_governance.finalize_annual_close_v1(jsonb,text)',
      'corporate_governance.finalize_annual_close_contract_v1(jsonb,text)',
      'FUNCTION corporate_governance.finalize_annual_close_v1',
      'FUNCTION corporate_governance.finalize_annual_close_contract_v1'
    )
  ) as inventory(
    active_signature, backup_signature, active_name, backup_name
  )
  loop
    if pg_catalog.to_regprocedure(routine.backup_signature) is not null then
      continue;
    end if;
    v_definition := pg_catalog.pg_get_functiondef(
      pg_catalog.to_regprocedure(routine.active_signature)
    );
    v_definition := pg_catalog.replace(
      v_definition, routine.active_name, routine.backup_name
    );
    execute v_definition;
  end loop;
end
$preserve_contract_writers$;

-- A contract rollback may be followed by the additive lifecycle rollback.
-- Restore its private backup names, but keep every money-moving backup fail
-- closed so a chained rollback cannot reactivate finalization or payment.
create or replace function
corporate_governance.owner_dividend_lifecycle_pre148_v1(
  p_decision_id uuid, p_replayed boolean
)
returns jsonb language plpgsql stable security definer set search_path = ''
as $function$
declare
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_finalization corporate_governance.owner_dividend_finalizations%rowtype;
  v_paid_ore bigint;
  v_latest_payment_entry_id uuid;
  v_state text;
begin
  select decision.* into v_decision
  from corporate_governance.owner_dividend_decisions decision
  where decision.id = p_decision_id;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  select finalization.* into v_finalization
  from corporate_governance.owner_dividend_finalizations finalization
  where finalization.decision_id = p_decision_id;
  select coalesce(pg_catalog.sum(payment.payment_amount_ore), 0)
  into v_paid_ore
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = p_decision_id;
  select payment.accounting_entry_id into v_latest_payment_entry_id
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = p_decision_id
  order by payment.created_at desc, payment.id desc
  limit 1;

  v_state := case
    when v_paid_ore = v_decision.declared_amount_ore then 'paid'
    when v_paid_ore > 0 then 'partially_paid'
    when v_finalization.id is not null then 'finalized'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'facts_approved'
    ) then 'facts_approved'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'documents_registered'
    ) then 'documents_registered'
    else 'proposed'
  end;
  return pg_catalog.jsonb_build_object(
    'decisionId', v_decision.id,
    'documentSetId', v_decision.document_set_id,
    'companyId', v_decision.company_id,
    'incomeYear', v_decision.income_year,
    'decisionHash', v_decision.decision_hash,
    'state', v_state,
    'declaredAmountOre', v_decision.declared_amount_ore,
    'paidAmountOre', v_paid_ore,
    'remainingAmountOre', v_decision.declared_amount_ore - v_paid_ore,
    'finalizationId', v_finalization.id,
    'accountingEntryId', coalesce(
      v_latest_payment_entry_id, v_finalization.accounting_entry_id
    ),
    'replayed', p_replayed
  );
end;
$function$;

create or replace function
corporate_governance.prepare_owner_dividend_finalization_pre148_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_finalization_pre148_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_payment_pre148_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.prepare_owner_dividend_finalization_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_finalization_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.prepare_owner_dividend_payment_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_payment_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

create or replace function
corporate_governance.finalize_annual_close_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_rollback_write_blocked';
end;
$function$;

revoke all on function
  corporate_governance.prepare_owner_dividend_finalization_contract_v1(
    jsonb, text
  ),
  corporate_governance.complete_owner_dividend_finalization_contract_v1(
    jsonb, text
  ),
  corporate_governance.prepare_owner_dividend_payment_contract_v1(jsonb, text),
  corporate_governance.complete_owner_dividend_payment_contract_v1(jsonb, text),
  corporate_governance.finalize_annual_close_contract_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
reset role;

create table if not exists public.corporate_accounting_policies (
  policy_version text primary key,
  declaration_debit_account text not null,
  dividend_payable_account text not null,
  bank_account text not null,
  reviewer text not null,
  reviewed_at timestamptz not null,
  evidence_reference text not null,
  supersedes_policy_version text,
  enabled boolean not null,
  recorded_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_decisions (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_kind text not null,
  annual_close_source_id uuid,
  source_hash text not null,
  canonical_input jsonb not null,
  decision_hash text not null,
  supersedes_decision_id uuid,
  created_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_document_sets (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null unique,
  template_family text not null,
  template_version text not null,
  decision_hash text not null,
  supersedes_set_id uuid,
  created_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_document_artifacts (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  set_id uuid not null,
  artifact_kind text not null,
  variant text not null,
  document_id uuid not null,
  content_sha256 text not null,
  byte_length bigint not null,
  mime_type text not null,
  storage_key text not null,
  supersedes_artifact_id uuid,
  created_by uuid not null,
  created_at timestamptz not null,
  unique (set_id, artifact_kind, variant),
  unique (storage_key)
);

create table if not exists public.corporate_document_events (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null,
  set_id uuid not null,
  artifact_id uuid,
  event_kind text not null,
  actor_id uuid not null,
  occurred_at timestamptz not null,
  decision_hash text not null,
  content_sha256 text,
  metadata jsonb not null,
  idempotency_key text not null unique,
  created_at timestamptz not null
);

create table if not exists public.corporate_decision_finalizations (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null unique,
  finalization_kind text not null,
  holding_action_id uuid,
  ledger_entry_id uuid,
  annual_close_source_id uuid,
  decision_hash text not null,
  signed_artifact_hashes jsonb not null,
  accounting_policy_version text,
  created_by uuid not null,
  created_at timestamptz not null
);

-- The predecessor projection is read-only after contract rollback, but the
-- original owner-dividend cutover needs these private deterministic helpers
-- when a full additive rollback is subsequently re-cut over. Restore their
-- exact pre-contract definitions while keeping all browser execution revoked.
create or replace function public.canonical_corporate_json_text(p_value jsonb)
returns text
language plpgsql
immutable
strict
set search_path = public, pg_temp
as $$
declare
  v_type text := jsonb_typeof(p_value);
  v_result text;
begin
  if v_type = 'object' then
    select '{' || coalesce(string_agg(to_jsonb(item.key)::text || ':' || public.canonical_corporate_json_text(item.value), ',' order by item.key), '') || '}'
      into v_result
    from jsonb_each(p_value) item;
    return v_result;
  elsif v_type = 'array' then
    select '[' || coalesce(string_agg(public.canonical_corporate_json_text(item.value), ',' order by item.ordinality), '') || ']'
      into v_result
    from jsonb_array_elements(p_value) with ordinality item(value, ordinality);
    return v_result;
  end if;
  return p_value::text;
end;
$$;

revoke all on function public.canonical_corporate_json_text(jsonb)
  from public, anon, authenticated;

create or replace function public.assert_corporate_decision_persisted_facts(
  p_company_id uuid,
  p_income_year integer,
  p_decision_kind text,
  p_annual_close_source_id uuid,
  p_canonical_input jsonb,
  p_decision_hash text
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_company public.companies%rowtype;
  v_source public.annual_data%rowtype;
  v_setup public.opening_balance_setups%rowtype;
  v_financial_totals jsonb := p_canonical_input -> 'financial_totals';
  v_shareholders jsonb := p_canonical_input -> 'shareholders';
  v_board_participants jsonb := p_canonical_input -> 'board_participants';
  v_confirmations jsonb := p_canonical_input -> 'confirmations';
  v_dividend jsonb := p_canonical_input -> 'dividend';
  v_cash_ore bigint;
  v_result_ore bigint;
  v_equity_ore bigint;
  v_available_distribution_ore bigint;
  v_shareholder_count integer;
  v_total_shares bigint;
  v_dividend_amount_ore bigint;
begin
  if jsonb_typeof(p_canonical_input) <> 'object'
    or jsonb_typeof(v_financial_totals) <> 'object'
    or jsonb_typeof(v_shareholders) <> 'array'
    or jsonb_typeof(v_board_participants) <> 'array'
    or jsonb_typeof(v_confirmations) <> 'object' then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;
  if p_decision_hash !~ '^[0-9a-f]{64}$'
    or encode(digest(public.canonical_corporate_json_text(p_canonical_input), 'sha256'), 'hex') <> p_decision_hash then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  select c.* into v_company
  from public.companies c
  where c.id = p_company_id;
  if not found
    or v_company.entity_type <> 'AS'
    or p_canonical_input ->> 'company_id' <> p_company_id::text
    or (p_canonical_input ->> 'income_year')::integer <> p_income_year
    or p_canonical_input ->> 'decision_kind' <> p_decision_kind
    or p_canonical_input ->> 'organization_number' <> v_company.org_number
    or p_canonical_input ->> 'legal_name' <> v_company.name
    or p_canonical_input ->> 'annual_close_source_id' <> p_annual_close_source_id::text
    or p_canonical_input ->> 'template_family' <> 'norwegian_simple_as'
    or p_canonical_input ->> 'template_version' <> 'corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1' then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  select a.* into v_source
  from public.annual_data a
  where a.id = p_annual_close_source_id
    and a.company_id = p_company_id
    and a.income_year = (p_canonical_input ->> 'annual_basis_year')::integer;
  if not found
    or (
      p_decision_kind = 'annual_close'
      and v_source.income_year <> p_income_year
    )
    or (
      p_decision_kind = 'owner_dividend'
      and (
        v_source.income_year > p_income_year
        or v_source.answers ->> 'general_meeting_approved' <> 'true'
        or exists (
          select 1
          from public.annual_data newer
          where newer.company_id = p_company_id
            and newer.income_year <= p_income_year
            and newer.income_year > v_source.income_year
            and newer.answers ->> 'general_meeting_approved' = 'true'
        )
      )
    ) then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  with ledger_lines as (
    select line
    from public.ledger_entries entry
    cross join lateral jsonb_array_elements(entry.lines) line
    where entry.company_id = p_company_id
      and entry.income_year = v_source.income_year
  ), totals as (
    select
      coalesce(sum(
        case when line ->> 'account' = '1920'
          then coalesce((line ->> 'debit')::numeric, 0) - coalesce((line ->> 'credit')::numeric, 0)
          else 0 end
      ), 0) as bank_balance,
      coalesce(sum(
        case when line ->> 'account' in ('8070', '8050')
          then coalesce((line ->> 'credit')::numeric, 0) - coalesce((line ->> 'debit')::numeric, 0)
          else 0 end
      ), 0) as financial_income,
      coalesce(sum(
        case when line ->> 'account' in ('7770', '6700', '6705', '6420', '7790', '6720', '7795')
          then coalesce((line ->> 'debit')::numeric, 0)
          else 0 end
      ), 0) as admin_costs,
      coalesce(sum(
        case when line ->> 'account' = '8090'
          then coalesce((line ->> 'debit')::numeric, 0)
          else 0 end
      ), 0) as financial_costs,
      coalesce(sum(
        case when line ->> 'account' = '2000'
          then coalesce((line ->> 'credit')::numeric, 0) - coalesce((line ->> 'debit')::numeric, 0)
          else 0 end
      ), 0) as share_capital,
      coalesce(sum(
        case when line ->> 'account' = '2050'
          then coalesce((line ->> 'credit')::numeric, 0) - coalesce((line ->> 'debit')::numeric, 0)
          else 0 end
      ), 0) as retained_earnings
    from ledger_lines
  )
  select
    round(bank_balance * 100)::bigint,
    round((financial_income - admin_costs - financial_costs) * 100)::bigint,
    round((share_capital + retained_earnings + financial_income - admin_costs - financial_costs) * 100)::bigint,
    greatest(0, round((retained_earnings + financial_income - admin_costs - financial_costs) * 100)::bigint)
  into v_cash_ore, v_result_ore, v_equity_ore, v_available_distribution_ore
  from totals;

  if (v_financial_totals ->> 'cash_ore')::bigint <> v_cash_ore
    or (v_financial_totals ->> 'result_after_tax_ore')::bigint <> v_result_ore
    or (v_financial_totals ->> 'equity_ore')::bigint <> v_equity_ore
    or (v_financial_totals ->> 'available_distribution_ore')::bigint <> v_available_distribution_ore
    or (p_canonical_input ->> 'annual_result_allocation_ore')::bigint <> v_result_ore then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  select setup.* into v_setup
  from public.opening_balance_setups setup
  where setup.company_id = p_company_id
    and setup.income_year = p_income_year;
  if not found then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;
  select count(*), coalesce(sum(shareholder.share_count), 0)
    into v_shareholder_count, v_total_shares
  from public.opening_shareholders shareholder
  where shareholder.company_id = p_company_id
    and shareholder.setup_id = v_setup.id;
  if v_shareholder_count = 0
    or v_total_shares <> v_setup.share_count
    or jsonb_array_length(v_shareholders) <> v_shareholder_count
    or (p_canonical_input ->> 'total_company_shares')::bigint <> v_total_shares
    or p_canonical_input ->> 'one_share_class_confirmed' <> 'true'
    or (
      select count(distinct item ->> 'shareholder_id')
      from jsonb_array_elements(v_shareholders) item
    ) <> v_shareholder_count
    or exists (
      select 1
      from public.opening_shareholders shareholder
      where shareholder.company_id = p_company_id
        and shareholder.setup_id = v_setup.id
        and not exists (
          select 1
          from jsonb_array_elements(v_shareholders) item
          where item ->> 'shareholder_id' = shareholder.id::text
            and item ->> 'name' = shareholder.name
            and (item ->> 'share_count')::bigint = shareholder.share_count
            and (item ->> 'represented_share_count')::bigint = shareholder.share_count
            and item ->> 'vote' = 'for'
        )
    ) then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  if jsonb_array_length(v_board_participants) = 0
    or (
      select count(distinct participant ->> 'participant_id')
      from jsonb_array_elements(v_board_participants) participant
    ) <> jsonb_array_length(v_board_participants)
    or (
      select count(*)
      from jsonb_array_elements(v_board_participants) participant
      where participant ->> 'role' = 'chair'
    ) <> 1
    or exists (
      select 1
      from jsonb_array_elements(v_board_participants) participant
      where btrim(coalesce(participant ->> 'participant_id', '')) = ''
        or btrim(coalesce(participant ->> 'name', '')) = ''
        or participant ->> 'role' not in ('chair', 'member')
    )
    or coalesce(p_canonical_input -> 'board_meeting' ->> 'meeting_date', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or coalesce(p_canonical_input -> 'board_meeting' ->> 'meeting_time', '') !~ '^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$'
    or btrim(coalesce(p_canonical_input -> 'board_meeting' ->> 'place', '')) = ''
    or p_canonical_input -> 'board_meeting' ->> 'treatment_method' not in ('physical', 'video', 'written')
    or coalesce(p_canonical_input -> 'general_meeting' ->> 'meeting_date', '') !~ '^\d{4}-\d{2}-\d{2}$'
    or coalesce(p_canonical_input -> 'general_meeting' ->> 'meeting_time', '') !~ '^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$'
    or btrim(coalesce(p_canonical_input -> 'general_meeting' ->> 'place', '')) = ''
    or p_canonical_input -> 'general_meeting' ->> 'meeting_form' not in ('physical', 'video')
    or btrim(coalesce(p_canonical_input -> 'general_meeting' ->> 'chair_name', '')) = ''
    or btrim(coalesce(p_canonical_input -> 'general_meeting' ->> 'co_signer_name', '')) = ''
    or (p_canonical_input -> 'general_meeting' ->> 'meeting_date')::date
      < (p_canonical_input -> 'board_meeting' ->> 'meeting_date')::date then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  if exists (
    select 1
    from unnest(array[
      'latest_approved_annual_accounts',
      'supported_dividend_basis',
      'full_board_participation',
      'full_share_representation',
      'unanimous_board',
      'unanimous_shareholders',
      'proportional_allocation',
      'prudent_equity_and_liquidity'
    ]) required_confirmation
    where v_confirmations ->> required_confirmation <> 'true'
  ) then
    raise exception 'corporate_documents_persisted_facts_mismatch';
  end if;

  if p_decision_kind = 'owner_dividend' then
    if jsonb_typeof(v_dividend) <> 'object'
      or coalesce(v_dividend ->> 'payment_date', '') !~ '^\d{4}-\d{2}-\d{2}$' then
      raise exception 'corporate_documents_persisted_facts_mismatch';
    end if;
    v_dividend_amount_ore := (v_dividend ->> 'amount_ore')::bigint;
    if v_dividend_amount_ore <= 0
      or v_dividend_amount_ore > v_available_distribution_ore
      or v_dividend_amount_ore > v_cash_ore
      or (v_dividend ->> 'liquidity_after_payment_ore')::bigint <> v_cash_ore - v_dividend_amount_ore
      or (v_dividend ->> 'payment_date')::date
        < (p_canonical_input -> 'general_meeting' ->> 'meeting_date')::date
      or jsonb_typeof(v_dividend -> 'allocations') <> 'array'
      or jsonb_array_length(v_dividend -> 'allocations') <> v_shareholder_count
      or (
        select count(distinct allocation ->> 'shareholder_id')
        from jsonb_array_elements(v_dividend -> 'allocations') allocation
      ) <> v_shareholder_count
      or (
        select coalesce(sum((allocation ->> 'amount_ore')::bigint), 0)
        from jsonb_array_elements(v_dividend -> 'allocations') allocation
      ) <> v_dividend_amount_ore then
      raise exception 'corporate_documents_persisted_facts_mismatch';
    end if;

    if exists (
      with proportional as (
        select
          shareholder.id::text as shareholder_id,
          floor(v_dividend_amount_ore::numeric * shareholder.share_count / v_total_shares)::bigint as base_ore,
          mod(v_dividend_amount_ore::numeric * shareholder.share_count, v_total_shares)::bigint as remainder
        from public.opening_shareholders shareholder
        where shareholder.company_id = p_company_id
          and shareholder.setup_id = v_setup.id
      ), ranked as (
        select
          proportional.*,
          row_number() over (order by remainder desc, shareholder_id) as remainder_rank,
          v_dividend_amount_ore - sum(base_ore) over () as remainder_ore
        from proportional
      ), expected as (
        select
          shareholder_id,
          base_ore + case when remainder_rank <= remainder_ore then 1 else 0 end as amount_ore
        from ranked
      )
      select 1
      from expected
      left join lateral (
        select (allocation ->> 'amount_ore')::bigint as amount_ore
        from jsonb_array_elements(v_dividend -> 'allocations') allocation
        where allocation ->> 'shareholder_id' = expected.shareholder_id
      ) actual on true
      where actual.amount_ore is null
        or actual.amount_ore <= 0
        or actual.amount_ore <> expected.amount_ore
    ) then
      raise exception 'corporate_documents_persisted_facts_mismatch';
    end if;
  elsif p_decision_kind = 'annual_close' then
    if v_dividend is distinct from 'null'::jsonb then
      raise exception 'corporate_documents_persisted_facts_mismatch';
    end if;
  else
    raise exception 'corporate_documents_unsupported_decision_kind';
  end if;
end;
$$;

revoke all on function public.assert_corporate_decision_persisted_facts(uuid, integer, text, uuid, jsonb, text)
  from public, anon, authenticated;

insert into public.corporate_accounting_policies
select * from corporate_governance.owner_dividend_accounting_policies;

insert into public.corporate_decisions
select
  decision.id, decision.company_id, decision.income_year,
  'owner_dividend', decision.annual_close_source_id,
  decision.source_hash, decision.canonical_input, decision.decision_hash,
  decision.supersedes_decision_id, decision.created_by, decision.created_at
from corporate_governance.owner_dividend_decisions decision
union all
select
  decision.id, decision.company_id, decision.income_year,
  'annual_close', decision.annual_close_source_id,
  decision.source_hash, decision.canonical_input, decision.decision_hash,
  decision.supersedes_decision_id, decision.created_by, decision.created_at
from corporate_governance.annual_close_decisions decision;

insert into public.corporate_document_sets
select
  decision.document_set_id, decision.company_id, decision.income_year,
  decision.id, decision.canonical_input ->> 'templateFamily',
  decision.canonical_input ->> 'templateVersion', decision.decision_hash,
  decision.supersedes_document_set_id, decision.created_by,
  decision.created_at
from corporate_governance.owner_dividend_decisions decision
union all
select
  decision.document_set_id, decision.company_id, decision.income_year,
  decision.id, decision.canonical_input ->> 'templateFamily',
  decision.canonical_input ->> 'templateVersion', decision.decision_hash,
  decision.supersedes_document_set_id, decision.created_by,
  decision.created_at
from corporate_governance.annual_close_decisions decision;

insert into public.corporate_document_artifacts
select
  artifact.id, artifact.company_id, artifact.income_year,
  artifact.document_set_id, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  document.content_type, document.storage_key,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from corporate_governance.owner_dividend_artifacts artifact
join public.documents document on document.id = artifact.document_id
union all
select
  artifact.id, artifact.company_id, artifact.income_year,
  artifact.document_set_id, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  document.content_type, document.storage_key,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from corporate_governance.annual_close_artifacts artifact
join public.documents document on document.id = artifact.document_id;

insert into public.corporate_document_events
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id,
  case when event.event_kind = 'documents_registered'
    then 'generated' else event.event_kind end,
  event.created_by, event.occurred_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.owner_dividend_events event
union all
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id,
  case when event.event_kind = 'documents_registered'
    then 'generated' else event.event_kind end,
  event.created_by, event.occurred_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.annual_close_events event
union all
select
  payment.id, payment.company_id, payment.income_year,
  payment.decision_id, payment.document_set_id, null::uuid,
  'payment_recorded', payment.created_by, payment.occurred_at,
  payment.decision_hash, null::text,
  pg_catalog.jsonb_build_object(
    'bank_transaction_id', payment.bank_transaction_id,
    'holding_action_id', payment.holding_action_id,
    'ledger_entry_id', payment.accounting_entry_id,
    'amount_ore', payment.payment_amount_ore,
    'remaining_payable_ore', decision.declared_amount_ore - (
      select coalesce(pg_catalog.sum(earlier.payment_amount_ore), 0)
      from corporate_governance.owner_dividend_payments earlier
      where earlier.decision_id = payment.decision_id
        and (
          earlier.created_at < payment.created_at
          or (
            earlier.created_at = payment.created_at
            and earlier.id <= payment.id
          )
        )
    ),
    'accounting_policy_version', payment.accounting_policy_version
  ),
  'canonical-event:' || payment.id::text, payment.created_at
from corporate_governance.owner_dividend_payments payment
join corporate_governance.owner_dividend_decisions decision
  on decision.id = payment.decision_id
union all
select
  finalization.event_id, finalization.company_id,
  finalization.income_year, finalization.decision_id,
  finalization.document_set_id, null::uuid, 'finalized',
  finalization.created_by, finalization.occurred_at,
  finalization.decision_hash, null::text,
  pg_catalog.jsonb_build_object(
    'finalization_id', finalization.id,
    'finalization_kind', 'owner_dividend_declared',
    'signed_artifact_hashes', finalization.signed_artifact_hashes,
    'accounting_policy_version', finalization.accounting_policy_version
  ),
  'canonical-event:' || finalization.event_id::text,
  finalization.created_at
from corporate_governance.owner_dividend_finalizations finalization
union all
select
  finalization.event_id, finalization.company_id,
  finalization.income_year, finalization.decision_id,
  finalization.document_set_id, null::uuid, 'finalized',
  finalization.created_by, finalization.occurred_at,
  finalization.decision_hash, null::text,
  pg_catalog.jsonb_build_object(
    'finalization_id', finalization.id,
    'finalization_kind', 'annual_close_adopted',
    'signed_artifact_hashes', finalization.signed_artifact_hashes,
    'accounting_policy_version', null
  ),
  'canonical-event:' || finalization.event_id::text,
  finalization.created_at
from corporate_governance.annual_close_finalizations finalization;

insert into public.corporate_decision_finalizations
select
  item.id, item.company_id, item.income_year, item.decision_id,
  'owner_dividend_declared', item.holding_action_id,
  item.accounting_entry_id, null::uuid, item.decision_hash,
  item.signed_artifact_hashes, item.accounting_policy_version,
  item.created_by, item.created_at
from corporate_governance.owner_dividend_finalizations item
union all
select
  item.id, item.company_id, item.income_year, item.decision_id,
  'annual_close_adopted', null::uuid, null::uuid, item.annual_close_source_id,
  item.decision_hash, item.signed_artifact_hashes, null,
  item.created_by, item.created_at
from corporate_governance.annual_close_finalizations item;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, document_id, risk_level,
  blocker_code, created_by, created_at
)
select
  loan.action_id, loan.company_id, loan.income_year, 'shareholder_loan',
  loan.loan_date, pg_catalog.jsonb_build_object(
    'loan_date', loan.loan_date,
    'amount', loan.amount_ore / 100.0,
    'direction', loan.direction,
    'counterparty_name', loan.counterparty_name,
    'document_status', loan.document_status,
    'interest_modelled', loan.interest_modelled,
    'related_party_security', loan.related_party_security,
    'bank_transaction_id', loan.bank_transaction_id,
    'document_id', loan.document_id
  ), loan.accounting_entry_id, loan.bank_transaction_id, loan.document_id,
  'ready', null, loan.created_by, loan.created_at
from corporate_governance.shareholder_loans loan
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, document_id, risk_level, blocker_code,
  created_by, created_at
)
select
  item.holding_action_id, item.company_id, item.income_year,
  'dividend_to_owner', item.created_at::date,
  decision.canonical_input || pg_catalog.jsonb_build_object(
    'action_kind', 'owner_dividend_declaration',
    'corporate_decision_id', item.decision_id,
    'accounting_policy_version', item.accounting_policy_version
  ), item.accounting_entry_id, artifact.document_id,
  'ready', null, item.created_by, item.created_at
from corporate_governance.owner_dividend_finalizations item
join corporate_governance.owner_dividend_decisions decision
  on decision.id = item.decision_id
left join corporate_governance.owner_dividend_artifacts artifact
  on artifact.decision_id = item.decision_id
  and artifact.artifact_kind = 'dividend_general_meeting_minutes'
  and artifact.variant = 'signed_owner_attested'
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, risk_level, blocker_code,
  created_by, created_at
)
select
  item.holding_action_id, item.company_id, item.income_year,
  'dividend_to_owner', item.bank_transaction_date,
  pg_catalog.jsonb_build_object(
    'action_kind', 'owner_dividend_payment',
    'corporate_decision_id', item.decision_id,
    'amount_ore', item.payment_amount_ore,
    'accounting_policy_version', item.accounting_policy_version
  ), item.accounting_entry_id, item.bank_transaction_id,
  'ready', null, item.created_by, item.created_at
from corporate_governance.owner_dividend_payments item
on conflict (id) do nothing;

grant select on
  public.corporate_accounting_policies,
  public.corporate_decisions,
  public.corporate_document_sets,
  public.corporate_document_artifacts,
  public.corporate_document_events,
  public.corporate_decision_finalizations
to authenticated;
revoke insert, update, delete on
  public.corporate_accounting_policies,
  public.corporate_decisions,
  public.corporate_document_sets,
  public.corporate_document_artifacts,
  public.corporate_document_events,
  public.corporate_decision_finalizations
from public, anon, authenticated, service_role;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$archive_authority$;
reset role;

do $archive_sources$
declare
  table_name text;
begin
  foreach table_name in array array[
    'owner_dividend_decisions', 'owner_dividend_artifacts',
    'owner_dividend_events', 'owner_dividend_finalizations',
    'owner_dividend_payments', 'shareholder_loans',
    'annual_close_decisions', 'annual_close_artifacts',
    'annual_close_events', 'annual_close_finalizations'
  ] loop
    execute pg_catalog.format(
      'drop trigger if exists %I on corporate_governance.%I',
      'company_archive_track_' || table_name, table_name
    );
  end loop;
  foreach table_name in array array[
    'corporate_decisions', 'corporate_document_sets',
    'corporate_document_artifacts', 'corporate_document_events',
    'corporate_decision_finalizations'
  ] loop
    execute pg_catalog.format(
      'create trigger %I before insert or update or delete on public.%I for each row execute function public.company_archive_track_source_write_v1(%L, %L)',
      'company_archive_track_' || table_name,
      table_name, 'year', 'company_id'
    );
  end loop;
end
$archive_sources$;

set local role company_archive_projection_executor;
do $archive_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$archive_authority_revoke$;
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke company_archive_projection_executor from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$membership_revoke$;

commit;
