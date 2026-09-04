-- Company-access-owned identity query for atomic governance workflows (#148).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.set_config(
  'talli.company_access_governance_identity_principal',
  current_user,
  true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant company_access_executor to %I',
    pg_catalog.current_setting(
      'talli.company_access_governance_identity_principal'
    )
  );
end
$membership$;

-- The restricted query composes company identity with governance facts in one
-- transaction without granting the workflow direct table access.
grant create on schema public to company_access_executor;
set local role company_access_executor;
create or replace function public.company_access_read_company_identity_v1(
  p_company_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_result jsonb;
begin
  if p_company_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or public.company_access_auth_uid_v1()
      is distinct from p_verified_subject::uuid
  then
    raise exception 'company_access_forbidden';
  end if;

  select pg_catalog.jsonb_build_object(
    'companyId', company.id,
    'organizationNumber', company.org_number,
    'legalName', company.name
  )
  into v_result
  from public.companies company
  where company.id = p_company_id;

  if v_result is null then
    raise exception 'company_access_not_found';
  end if;
  return v_result;
end;
$function$;
reset role;
revoke create on schema public from company_access_executor;

revoke all on function
  public.company_access_read_company_identity_v1(uuid, text)
from public, anon, authenticated, service_role;
grant execute on function
  public.company_access_read_company_identity_v1(uuid, text)
to corporate_governance_workflow_executor;

do $membership$
begin
  execute pg_catalog.format(
    'revoke company_access_executor from %I',
    pg_catalog.current_setting(
      'talli.company_access_governance_identity_principal'
    )
  );
end
$membership$;

commit;
