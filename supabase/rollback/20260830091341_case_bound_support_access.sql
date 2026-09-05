-- Safe #200 rollback: preserve grants, immutable receipts, openings, audits and
-- deletion-review bindings while disabling every support authorization seam.
-- Customer/member behavior stays available; standing operator access is never
-- restored. Reapplying the forward migration re-enables the same evidence.
begin;

do $borrow_billing_policy_owner$
begin
  if pg_catalog.to_regclass('billing.billing_accounts') is not null then
    execute pg_catalog.format('grant billing_store_owner to %I', current_user);
  end if;
end
$borrow_billing_policy_owner$;

drop policy if exists support_access_grants_executor_select on public.support_access_grants;
drop policy if exists support_access_grants_executor_insert on public.support_access_grants;
drop policy if exists support_access_grants_executor_update on public.support_access_grants;
drop policy if exists support_access_receipts_executor on public.support_access_operation_receipts;
drop policy if exists support_case_openings_executor on public.support_case_openings;

drop policy if exists support_case_read_audit_events on public.audit_events;
drop policy if exists support_case_read_filing_submissions on public.filing_submissions;
drop policy if exists support_case_read_filing_readiness on public.filing_readiness_snapshots;
do $drop_billing_support_policies$
begin
  if pg_catalog.to_regclass('billing.billing_accounts') is not null then
    drop policy if exists support_case_read_billing_accounts on billing.billing_accounts;
    drop policy if exists support_case_read_billing_events on billing.billing_payment_events;
  else
    drop policy if exists support_case_read_billing_accounts on public.billing_accounts;
    drop policy if exists support_case_read_billing_events on public.billing_payment_events;
  end if;
end
$drop_billing_support_policies$;
drop policy if exists support_case_read_authority_permissions on public.authority_permissions;
drop policy if exists support_case_read_authority_runs on public.authority_test_runs;
drop policy if exists support_case_read_system_user_requests on public.system_user_requests;
do $drop_pilot_support_policy$
begin
  if pg_catalog.to_regclass('billing.production_pilot_entitlements') is not null then
    drop policy if exists support_case_read_pilot_entitlements on billing.production_pilot_entitlements;
  else
    drop policy if exists support_case_read_pilot_entitlements on public.production_pilot_entitlements;
  end if;
end
$drop_pilot_support_policy$;
drop policy if exists support_case_read_approval_snapshots on public.filing_approval_snapshots;
drop policy if exists support_case_read_production_submissions on public.production_filing_submissions;
drop policy if exists support_case_read_production_events on public.production_filing_events;
drop policy if exists support_case_read_feedback_artifacts on public.production_feedback_artifacts;
drop policy if exists support_case_read_documents on public.documents;
drop policy if exists support_case_read_storage_objects on storage.objects;
revoke usage on schema storage from company_access_executor;

do $borrow_support_function_owner$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
end
$borrow_support_function_owner$;

set role company_access_executor;

create or replace function public.company_access_has_open_support_case_v1(
  p_case_id uuid,
  p_company_id uuid,
  p_scope text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select false;
$function$;

reset role;
revoke create on schema public from company_access_executor;

create or replace function public.company_access_support_review_operation_available_v1(
  p_operation_id uuid,
  p_support_case_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select false;
$function$;

do $disable_support_functions$
begin
  alter function public.company_access_grant_support_access(
    uuid, uuid, uuid, text, text[], timestamptz, timestamptz
  ) owner to current_user;
  alter function public.company_access_revoke_support_access(uuid, uuid, text)
    owner to current_user;
  alter function public.company_access_open_support_case(uuid, uuid)
    owner to current_user;
  alter function public.company_access_read_support_case(uuid)
    owner to current_user;
  alter function public.company_access_review_deletion(
    uuid, uuid, uuid, uuid, timestamptz, text, text
  ) owner to current_user;
  alter function public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, uuid, integer, text, timestamptz, text, text
  ) owner to current_user;
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'billing_store_owner') then
    execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
  end if;
end
$disable_support_functions$;

revoke all on function public.company_access_grant_support_access(
  uuid, uuid, uuid, text, text[], timestamptz, timestamptz
), public.company_access_revoke_support_access(uuid, uuid, text),
  public.company_access_open_support_case(uuid, uuid),
  public.company_access_read_support_case(uuid),
  public.company_access_review_deletion(
    uuid, uuid, uuid, uuid, timestamptz, text, text
  ), public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, uuid, integer, text, timestamptz, text, text
  ), public.company_access_support_review_operation_available_v1(uuid, uuid),
  public.company_access_is_active_support_operator_v1(uuid)
from public, anon, authenticated, service_role, company_access_executor;

commit;
