-- Company identity is established from Brreg during insert and is immutable to
-- the authenticated Data API afterwards. Controlled refreshes require a future
-- privileged workflow with explicit audit evidence.
revoke update on public.companies from authenticated;
drop policy if exists "owners can lock their new company identity" on public.companies;

-- Membership acceptance uses an invitation-backed INSERT. No client role needs
-- UPDATE, and allowing a member to update their own row would let them replace
-- reviewer/read_only with owner.
revoke update on public.company_memberships from authenticated;
drop policy if exists "owners can update their own membership acceptance" on public.company_memberships;

-- Reviewers/read-only users must enter through company_invitations and the
-- invitation-backed INSERT policy, not through a direct owner-created member.
drop policy if exists "owners can invite company members" on public.company_memberships;
