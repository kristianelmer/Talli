-- Supabase projects created after the April 2026 Data API change no longer
-- expose newly created public objects through implicit grants. Keep anonymous
-- access closed and make the server-only service role explicit. Authenticated
-- access remains the least-privilege, per-object grants in migrations 0001-0004.
revoke all privileges on all tables in schema public from anon;
revoke all privileges on all sequences in schema public from anon;

grant usage on schema public to service_role;
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;
grant all privileges on all functions in schema public to service_role;

alter default privileges for role postgres in schema public
  revoke all privileges on tables from anon;
alter default privileges for role postgres in schema public
  revoke all privileges on sequences from anon;
alter default privileges for role postgres in schema public
  grant all privileges on tables to service_role;
alter default privileges for role postgres in schema public
  grant all privileges on sequences to service_role;
alter default privileges for role postgres in schema public
  grant all privileges on functions to service_role;

-- Public-schema SECURITY DEFINER helpers are not anonymous API endpoints.
-- The invitation helpers remain callable only by signed-in users because RLS
-- policies depend on them; the mutation guard is invoked only as a trigger.
revoke all on function public.can_accept_company_invitation(uuid, text)
  from public, anon;
grant execute on function public.can_accept_company_invitation(uuid, text)
  to authenticated, service_role;

revoke all on function public.is_company_creator(uuid)
  from public, anon;
grant execute on function public.is_company_creator(uuid)
  to authenticated, service_role;

revoke all on function public.prevent_corporate_record_mutation()
  from public, anon, authenticated;
grant execute on function public.prevent_corporate_record_mutation()
  to service_role;

-- Cache the request JWT once per statement instead of recomputing it for every
-- invitation row. This matches Supabase's current RLS advisor guidance.
alter policy "owners and invitees can read company invitations"
on public.company_invitations
using (
  invited_email = lower(coalesce(((select auth.jwt()) ->> 'email'), ''))
  or exists (
    select 1
    from public.company_memberships m
    where m.company_id = company_invitations.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

alter policy "owners and invitees can update company invitations"
on public.company_invitations
using (
  invited_email = lower(coalesce(((select auth.jwt()) ->> 'email'), ''))
  or exists (
    select 1
    from public.company_memberships m
    where m.company_id = company_invitations.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  (
    status = 'accepted'
    and accepted_by = (select auth.uid())
    and invited_email = lower(coalesce(((select auth.jwt()) ->> 'email'), ''))
  )
  or (
    invited_by = (select auth.uid())
    and exists (
      select 1
      from public.company_memberships m
      where m.company_id = company_invitations.company_id
        and m.user_id = (select auth.uid())
        and m.role = 'owner'
    )
  )
);
