-- HoldingSwift bank suggestions: deterministic rules with explicit, atomic owner acceptance.

create table if not exists public.bank_suggestion_acceptances (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  bank_transaction_id uuid not null references public.bank_transactions(id) on delete restrict,
  ledger_entry_id uuid not null references public.ledger_entries(id) on delete restrict,
  rule_id text not null check (rule_id in ('bank_fee', 'system_subscription', 'deposit_interest')),
  rule_version text not null check (rule_version <> ''),
  reason text not null check (reason <> ''),
  lines jsonb not null check (jsonb_typeof(lines) = 'array'),
  accepted_by uuid not null references auth.users(id) on delete restrict,
  accepted_at timestamptz not null default now(),
  unique (bank_transaction_id),
  unique (ledger_entry_id)
);

create index if not exists bank_suggestion_acceptances_company_idx
  on public.bank_suggestion_acceptances(company_id);

alter table public.bank_suggestion_acceptances enable row level security;

grant select on public.bank_suggestion_acceptances to authenticated;
revoke insert, update, delete on public.bank_suggestion_acceptances from authenticated;

drop policy if exists "company members can read bank suggestion acceptances"
  on public.bank_suggestion_acceptances;
create policy "company members can read bank suggestion acceptances"
on public.bank_suggestion_acceptances for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = bank_suggestion_acceptances.company_id
      and m.user_id = (select auth.uid())
  )
);

create or replace function public.accept_bank_transaction_suggestion(
  p_bank_transaction_id uuid,
  p_rule_id text,
  p_rule_version text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_transaction public.bank_transactions%rowtype;
  v_existing public.bank_suggestion_acceptances%rowtype;
  v_entry_id uuid := gen_random_uuid();
  v_acceptance_id uuid := gen_random_uuid();
  v_text text;
  v_bank_fee_match boolean;
  v_subscription_match boolean;
  v_interest_match boolean;
  v_match_count integer;
  v_amount numeric(20, 2);
  v_reason text;
  v_lines jsonb;
  v_row_count integer;
begin
  if v_actor_id is null then
    raise exception 'authentication_required';
  end if;
  if p_bank_transaction_id is null then
    raise exception 'bank_transaction_not_found';
  end if;

  select * into v_transaction
  from public.bank_transactions
  where id = p_bank_transaction_id
  for update;
  if not found then
    raise exception 'bank_transaction_not_found';
  end if;

  if not exists (
    select 1
    from public.company_memberships m
    where m.company_id = v_transaction.company_id
      and m.user_id = v_actor_id
      and m.role = 'owner'
  ) then
    raise exception 'company_owner_required';
  end if;
  if exists (
    select 1
    from public.period_locks pl
    where pl.company_id = v_transaction.company_id
      and pl.income_year = v_transaction.income_year
  ) then
    raise exception 'income_year_locked';
  end if;

  select * into v_existing
  from public.bank_suggestion_acceptances
  where bank_transaction_id = p_bank_transaction_id;
  if found then
    if v_existing.rule_id = p_rule_id
      and v_existing.rule_version = p_rule_version
      and v_transaction.matched_entry_id = v_existing.ledger_entry_id
    then
      return jsonb_build_object(
        'acceptance_id', v_existing.id,
        'ledger_entry_id', v_existing.ledger_entry_id,
        'idempotent', true
      );
    end if;
    raise exception 'bank_suggestion_acceptance_conflict';
  end if;

  if v_transaction.matched_entry_id is not null
    or v_transaction.matched_action_id is not null
    or v_transaction.accepted_warning
  then
    raise exception 'bank_transaction_already_reconciled';
  end if;
  if p_rule_version <> '2026-07-13.1' then
    raise exception 'bank_rule_version_mismatch';
  end if;

  v_text := lower(btrim(coalesce(v_transaction.text, '')));
  v_bank_fee_match := v_text ~ '(^|[^[:alnum:]])(årsgebyr|arsgebyr|bankgebyr|bank fee|annual fee)($|[^[:alnum:]])';
  v_subscription_match := v_text ~ '(^|[^[:alnum:]])(systemabonnement|system subscription)($|[^[:alnum:]])';
  v_interest_match := v_text ~ '(^|[^[:alnum:]])(renter|rente|interest)($|[^[:alnum:]])';
  v_match_count := v_bank_fee_match::integer
    + v_subscription_match::integer
    + v_interest_match::integer;

  if v_match_count > 1 then
    raise exception 'bank_suggestion_ambiguous';
  end if;
  if v_match_count = 0
    or (p_rule_id = 'bank_fee' and not v_bank_fee_match)
    or (p_rule_id = 'system_subscription' and not v_subscription_match)
    or (p_rule_id = 'deposit_interest' and not v_interest_match)
    or p_rule_id not in ('bank_fee', 'system_subscription', 'deposit_interest')
  then
    raise exception 'bank_suggestion_rule_mismatch';
  end if;

  if ((p_rule_id in ('bank_fee', 'system_subscription')) and v_transaction.amount >= 0)
    or (p_rule_id = 'deposit_interest' and v_transaction.amount <= 0)
  then
    raise exception 'bank_suggestion_direction_mismatch';
  end if;

  v_amount := round(abs(v_transaction.amount), 2);
  if v_amount <= 0 then
    raise exception 'bank_suggestion_direction_mismatch';
  end if;

  if p_rule_id = 'bank_fee' then
    v_reason := 'Teksten beskriver et bankgebyr og beløpet er en utbetaling.';
    v_lines := jsonb_build_array(
      jsonb_build_object('account', '7770', 'description', 'Bankomkostninger', 'debit', v_amount, 'credit', 0),
      jsonb_build_object('account', '1920', 'description', 'Bank', 'debit', 0, 'credit', v_amount)
    );
  elsif p_rule_id = 'system_subscription' then
    v_reason := 'Teksten beskriver et systemabonnement og beløpet er en utbetaling.';
    v_lines := jsonb_build_array(
      jsonb_build_object('account', '6700', 'description', 'Fremmede tjenester', 'debit', v_amount, 'credit', 0),
      jsonb_build_object('account', '1920', 'description', 'Bank', 'debit', 0, 'credit', v_amount)
    );
  else
    v_reason := 'Teksten beskriver renteinntekt og beløpet er en innbetaling.';
    v_lines := jsonb_build_array(
      jsonb_build_object('account', '1920', 'description', 'Bank', 'debit', v_amount, 'credit', 0),
      jsonb_build_object('account', '8050', 'description', 'Annen renteinntekt', 'debit', 0, 'credit', v_amount)
    );
  end if;

  insert into public.ledger_entries (
    id, company_id, income_year, entry_type, memo, lines, risk_flags, created_by
  ) values (
    v_entry_id,
    v_transaction.company_id,
    v_transaction.income_year,
    'bank_rule_suggestion',
    'Godkjent bankforslag: ' || v_transaction.text,
    v_lines,
    '[]'::jsonb,
    v_actor_id
  );

  insert into public.bank_suggestion_acceptances (
    id, company_id, bank_transaction_id, ledger_entry_id,
    rule_id, rule_version, reason, lines, accepted_by
  ) values (
    v_acceptance_id, v_transaction.company_id, v_transaction.id, v_entry_id,
    p_rule_id, p_rule_version, v_reason, v_lines, v_actor_id
  );

  update public.bank_transactions
  set matched_entry_id = v_entry_id
  where id = v_transaction.id
    and matched_entry_id is null
    and matched_action_id is null
    and not accepted_warning;
  get diagnostics v_row_count = row_count;
  if v_row_count <> 1 then
    raise exception 'bank_transaction_already_reconciled';
  end if;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_transaction.company_id,
    v_actor_id,
    'bank',
    'bank_suggestion_accepted',
    'Eier godkjente bankregel ' || p_rule_id || ' versjon ' || p_rule_version || '.'
  );

  return jsonb_build_object(
    'acceptance_id', v_acceptance_id,
    'ledger_entry_id', v_entry_id,
    'idempotent', false,
    'rule_id', p_rule_id,
    'rule_version', p_rule_version
  );
end;
$$;

revoke all on function public.accept_bank_transaction_suggestion(uuid, text, text) from public;
grant execute on function public.accept_bank_transaction_suggestion(uuid, text, text) to authenticated;
