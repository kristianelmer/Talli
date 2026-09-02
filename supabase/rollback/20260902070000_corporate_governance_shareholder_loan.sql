-- Reverse #145 only while every canonical loan is preserved in the predecessor projection.
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

lock table public.holding_actions in share row exclusive mode;
lock table corporate_governance.shareholder_loans in share row exclusive mode;

do $safety$
begin
  if exists (
    select 1
    from corporate_governance.shareholder_loans loan
    left join public.holding_actions action
      on action.id = loan.action_id
      and action.company_id = loan.company_id
      and action.income_year = loan.income_year
      and action.action_type = 'shareholder_loan'
      and action.ledger_entry_id = loan.accounting_entry_id
      and action.bank_transaction_id is not distinct from loan.bank_transaction_id
      and action.document_id is not distinct from loan.document_id
      and action.action_date = loan.loan_date
      and action.payload ->> 'direction' = loan.direction
      and pg_catalog.round(
        (action.payload ->> 'amount')::numeric * 100
      )::bigint = loan.amount_ore
    where action.id is null
  ) then
    raise exception 'corporate_governance_shareholder_loan_rollback_unsafe';
  end if;
end
$safety$;

revoke execute on function
  corporate_governance.prepare_shareholder_loan_v1(jsonb, text),
  corporate_governance.complete_shareholder_loan_v1(jsonb, text)
from corporate_governance_workflow_executor;
set local role corporate_governance_store_owner;
drop function corporate_governance.complete_shareholder_loan_v1(jsonb, text);
drop function corporate_governance.prepare_shareholder_loan_v1(jsonb, text);
drop function corporate_governance.shareholder_loan_result_v1(uuid, boolean);
drop trigger shareholder_loans_immutable
  on corporate_governance.shareholder_loans;
drop policy governance_owner_creates_shareholder_loans
  on corporate_governance.shareholder_loans;
drop policy governance_owner_reads_shareholder_loans
  on corporate_governance.shareholder_loans;
drop table corporate_governance.shareholder_loans;
reset role;

revoke execute on function backend_system.project_shareholder_loan_v1(
  jsonb, text
) from corporate_governance_store_owner;
set local role ledger_store_owner;
drop function backend_system.project_shareholder_loan_v1(jsonb, text);
reset role;

revoke execute on function banking.claim_corporate_governance_transaction_v1(
  jsonb, uuid, text
) from corporate_governance_workflow_executor;
revoke execute on function banking.prepare_shareholder_loan_transaction_v1(
  jsonb, text
) from corporate_governance_store_owner;
set local role banking_store_owner;
drop function banking.claim_corporate_governance_transaction_v1(
  jsonb, uuid, text
);
drop function banking.prepare_shareholder_loan_transaction_v1(jsonb, text);
reset role;

grant usage, create on schema ledger
to corporate_governance_ledger_bridge_owner;
set local role corporate_governance_ledger_bridge_owner;
create or replace function ledger.post_corporate_governance_entry_v1(
  p_idempotency_key text, p_company_id uuid, p_income_year integer,
  p_entry_kind text, p_memo text, p_lines jsonb,
  p_source_capability text, p_source_record_id text,
  p_correlation_id text, p_verified_subject text,
  p_requested_entry_id uuid
)
returns table (
  ledger_entry_id uuid, company_id uuid, income_year integer,
  entry_kind text, posted_at timestamptz, replayed boolean
)
language plpgsql security definer set search_path = ''
as $function$
begin
  if pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT'
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
