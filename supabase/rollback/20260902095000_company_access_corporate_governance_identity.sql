-- Remove the company-access-owned governance identity query (#148).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.set_config(
  'talli.company_access_governance_identity_rollback_principal',
  current_user,
  true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant company_access_executor to %I',
    pg_catalog.current_setting(
      'talli.company_access_governance_identity_rollback_principal'
    )
  );
end
$membership$;

revoke all on function
  public.company_access_read_company_identity_v1(uuid, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
set local role company_access_executor;
drop function if exists
  public.company_access_read_company_identity_v1(uuid, text);
reset role;

do $membership$
begin
  execute pg_catalog.format(
    'revoke company_access_executor from %I',
    pg_catalog.current_setting(
      'talli.company_access_governance_identity_rollback_principal'
    )
  );
end
$membership$;

commit;
