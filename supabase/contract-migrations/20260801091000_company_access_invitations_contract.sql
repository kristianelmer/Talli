-- CONTRACT RELEASE ARTIFACT: intentionally outside supabase/migrations so the
-- automatic deployment runner cannot apply it in the expansion release. Move
-- this immutable file into the runner only in Release C, after the generated-
-- client web/backend revision is live and its overlap checks pass.

drop policy if exists "owners and invitees can read company invitations" on public.company_invitations;
drop policy if exists "accepted owners and invitees can read company invitations" on public.company_invitations;
drop policy if exists "owners can create company invitations" on public.company_invitations;
drop policy if exists "owners and invitees can update company invitations" on public.company_invitations;
drop policy if exists "owners can invite company members" on public.company_memberships;
drop policy if exists "invited users can accept company memberships" on public.company_memberships;

drop policy if exists "accepted owners can read company invitations" on public.company_invitations;
create policy "accepted owners can read company invitations"
on public.company_invitations for select
to authenticated
using (public.company_access_is_accepted_owner_v1(company_id));

revoke insert, update, delete on public.company_invitations from authenticated;
revoke select on public.company_invitations from authenticated;
grant select (
  id, company_id, invited_email, invited_user_id, role, status, expires_at,
  invited_by, accepted_by, accepted_at, revoked_by, revoked_at, resent_at,
  delivery_events, created_at, updated_at
) on public.company_invitations to authenticated;

-- Keep table privileges needed by later serialized company-membership slices.
-- Their unrelated owner-onboarding policies remain intact; #160's invite/admin
-- policies above are the only membership compatibility surface contracted here.
