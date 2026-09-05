-- Remove the company-access-owned billing subject contract (#137).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

revoke all on function
  public.company_access_is_accepted_owner_subject_v1(uuid, uuid)
from public, anon, authenticated, service_role;
drop function if exists
  public.company_access_is_accepted_owner_subject_v1(uuid, uuid);

commit;
