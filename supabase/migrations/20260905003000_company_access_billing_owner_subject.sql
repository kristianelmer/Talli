-- Company-access-owned subject authorization contract for billing (#137).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

-- This narrow table-owner boundary mirrors the established current-actor
-- predicates. It exposes one boolean, requires a verified fresh admin caller,
-- and never grants the consumer access to membership rows.
create or replace function public.company_access_is_accepted_owner_subject_v1(
  p_company_id uuid,
  p_user_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
  and exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = p_company_id
      and membership.user_id = p_user_id
      and membership.role = 'owner'
      and membership.accepted_at is not null
  );
$function$;

revoke all on function
  public.company_access_is_accepted_owner_subject_v1(uuid, uuid)
from public, anon, authenticated, service_role;

commit;
