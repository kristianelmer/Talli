-- Safe rollback: preserve all historical/current acceptance evidence and make
-- new legal acceptance/admission fail closed until the forward migration is
-- reapplied. Never reactivate the superseded July issuance contract.
begin;

create or replace function public.company_access_has_current_agreement_v1(
  p_company_id uuid
)
returns boolean
language sql
stable
set search_path = ''
as $function$
  select false;
$function$;

drop policy if exists "company access appends current agreement evidence"
on public.customer_agreement_acceptances;
create policy "company access appends current agreement evidence"
on public.customer_agreement_acceptances for insert
to company_access_executor
with check (false);

do $disable_active_legal_writers$
declare
  v_signature text;
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  alter function public.company_access_reaccept_agreement(
    uuid, uuid, uuid, text, boolean, text, date, text, text,
    text, date, text, text, text, text
  ) owner to current_user;
  alter function public.company_access_admit_company_year(
    uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
    text,text,text,text,text,text,text,text,text,text,date,text,text,text,
    date,text,text,text,date,text,text,text,text
  ) owner to current_user;
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);

  foreach v_signature in array array[
    'public.append_company_agreement_acceptance(uuid,uuid,text,date,text,text,text,date,text,text,text,text)',
    'public.create_company_workspace_with_acceptance(uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text)'
  ] loop
    if pg_catalog.to_regprocedure(v_signature) is not null then
      execute pg_catalog.format(
        'revoke all on function %s from public, anon, authenticated, service_role',
        v_signature
      );
    end if;
  end loop;
end
$disable_active_legal_writers$;

revoke all on function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
), public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role, company_access_executor;

revoke all on function public.company_access_has_current_agreement_v1(uuid)
from public, anon, authenticated, service_role, company_access_executor,
  ledger_store_owner, ledger_workflow_store_owner;

commit;
