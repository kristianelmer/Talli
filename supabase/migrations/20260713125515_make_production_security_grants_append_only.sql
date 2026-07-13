-- Production-security approvals are durable evidence. Once created, the
-- approved actor, scope, approver, approval time and expiry must not be
-- rewritten. The only permitted update is a one-way revocation by an active
-- support admin, with the revoking operator recorded on the row.

alter table public.production_security_grants
add column if not exists revoked_by uuid references auth.users(id) on delete restrict;

create or replace function private.enforce_production_security_grant_revocation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.actor_id is distinct from old.actor_id
    or new.security_review_approved is distinct from old.security_review_approved
    or new.production_credentials_enabled is distinct from old.production_credentials_enabled
    or new.approved_by is distinct from old.approved_by
    or new.approved_at is distinct from old.approved_at
    or new.expires_at is distinct from old.expires_at
  then
    raise exception 'production security approval metadata is immutable';
  end if;

  if old.revoked_at is not null
    or new.revoked_at is null
  then
    raise exception 'production security grants support one-way revocation only';
  end if;

  new.revoked_at := now();
  new.revoked_by := auth.uid();
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.enforce_production_security_grant_revocation() from public, anon, authenticated;

drop trigger if exists enforce_production_security_grant_revocation
on public.production_security_grants;
create trigger enforce_production_security_grant_revocation
before update on public.production_security_grants
for each row execute function private.enforce_production_security_grant_revocation();

revoke update on public.production_security_grants from authenticated;
grant update (revoked_at) on public.production_security_grants to authenticated;

drop policy if exists "admins can update production security grants"
on public.production_security_grants;
drop policy if exists "admins can revoke production security grants"
on public.production_security_grants;
create policy "admins can revoke production security grants"
on public.production_security_grants for update
to authenticated
using (
  revoked_at is null
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
)
with check (
  revoked_at is not null
  and revoked_by = (select auth.uid())
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);
